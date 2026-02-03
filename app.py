import streamlit as st
import pandas as pd
import random
import re
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定と関数 ---
st.set_page_config(page_title="レッスン調整システム", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v2")

# 接続
conn = st.connection("gsheets", type=GSheetsConnection)

# 1. 候補日（Slots）の読み書き
def load_slots():
    try:
        df = conn.read(worksheet="Slots", usecols=[0], ttl=0)
        if df.empty or df.columns[0] != "候補日時":
            return []
        return df["候補日時"].dropna().tolist()
    except:
        return []

def save_slots(slot_list):
    df = pd.DataFrame({"候補日時": slot_list})
    conn.update(worksheet="Slots", data=df)

# 2. 希望（Requests）の読み書き
def load_requests():
    try:
        df = conn.read(worksheet="Requests", usecols=[0, 1], ttl=0)
        if df.shape[1] < 2: return pd.DataFrame(columns=["氏名", "希望枠"])
        return df.dropna(how="all")
    except:
        return pd.DataFrame(columns=["氏名", "希望枠"])

def save_requests(new_df):
    conn.update(worksheet="Requests", data=new_df)

# 3. 履歴（History）の読み書き
def load_history():
    try:
        df = conn.read(worksheet="History", usecols=[0, 1, 2], ttl=0)
        required = ["日時", "受講者", "学期"]
        if df.shape[1] < 3: return pd.DataFrame(columns=required)
        return df
    except:
        return pd.DataFrame(columns=["日時", "受講者", "学期"])

def save_history(new_records_df):
    # 既存の履歴に追加して保存
    old_df = load_history()
    # columnsを合わせる
    if old_df.empty:
        updated_df = new_records_df
    else:
        updated_df = pd.concat([old_df, new_records_df], ignore_index=True)
    conn.update(worksheet="History", data=updated_df)

# 学期判定ロジック
def get_semester(date_str):
    # "10/4..." のような文字列から月を抽出
    match = re.search(r'(\d+)/', date_str)
    if match:
        month = int(match.group(1))
        # 4月〜8月は前期、9月〜2月(3月)は後期
        if 4 <= month <= 8:
            return "前期 (4-8月)"
        else:
            return "後期 (9-2月)"
    return "不明"

# --- 画面構成 ---

# タブで機能を分ける
tab1, tab2, tab3 = st.tabs(["🙋 学生用: 希望提出", "📅 先生用: 日程調整・管理", "📊 データ集計"])

# ==========================================
# タブ1: 学生用 (希望入力)
# ==========================================
with tab1:
    st.header("希望スケジュールの入力")
    current_slots = load_slots() # シートから候補日を取得
    
    if not current_slots:
        st.warning("現在、募集中のレッスン枠はありません。")
    else:
        df_req = load_requests()
        
        with st.form("student_form"):
            student_name = st.text_input("氏名 (フルネーム)", placeholder="例: 松村泰佑")
            st.write("▼ 可能な日時にチェックを入れてください")
            
            # 過去の入力があれば反映
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]):
                    existing_wishes = row["希望枠"].split(",")
            
            selected = []
            cols = st.columns(2)
            for i, slot in enumerate(current_slots):
                is_checked = slot in existing_wishes
                if cols[i % 2].checkbox(slot, value=is_checked, key=f"s_{i}"):
                    selected.append(slot)
            
            if st.form_submit_button("送信 / 更新"):
                if not student_name:
                    st.error("名前を入れてください")
                else:
                    wishes_str = ",".join(selected)
                    new_row = {"氏名": student_name, "希望枠": wishes_str}
                    df_req = df_req[df_req["氏名"] != student_name] # 上書き用削除
                    new_df = pd.concat([df_req, pd.DataFrame([new_row])], ignore_index=True)
                    save_requests(new_df)
                    st.success(f"{student_name}さんの希望を保存しました！")
                    st.rerun()

# ==========================================
# タブ2: 先生用 (枠管理 & シフト作成)
# ==========================================
with tab2:
    st.header("管理者メニュー")
    
    # --- 1. 候補日の編集機能 ---
    with st.expander("📝 候補日（募集日程）の編集", expanded=False):
        st.caption("改行区切りで日時を入力し、保存を押すと「学生用画面」に反映されます。")
        current_slots = load_slots()
        default_text = "\n".join(current_slots)
        
        new_text = st.text_area("候補日リスト", value=default_text, height=200)
        
        if st.button("候補日を更新して保存"):
            # 空行を除去してリスト化
            new_list = [line.strip() for line in new_text.split('\n') if line.strip()]
            save_slots(new_list)
            st.success("候補日を更新しました！タブ1で確認できます。")
            st.rerun()

    st.markdown("---")
    
    # --- 2. シフト作成機能 ---
    st.subheader("シフト自動作成")
    if st.button("現在の希望でシフトを組む"):
        current_slots = load_slots()
        df_req = load_requests()
        
        if df_req.empty or not current_slots:
            st.error("データ不足です（学生の希望がない、または候補日がありません）")
        else:
            # ロジック実行
            req_dict = {}
            for _, row in df_req.iterrows():
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    req_dict[row["氏名"]] = row["希望枠"].split(",")
            
            final_schedule = {}
            student_counts = defaultdict(int)
            daily_counts = defaultdict(lambda: defaultdict(int))
            
            # 枠ごとの希望者
            slot_applicants = {s: [] for s in current_slots}
            for name, wishes in req_dict.items():
                for w in wishes:
                    if w in current_slots:
                        slot_applicants[w].append(name)
            
            # 希望少ない順に決定
            sorted_slots = sorted(
                [s for s in current_slots if slot_applicants[s]],
                key=lambda s: len(slot_applicants[s])
            )
            
            for slot in sorted_slots:
                cands = slot_applicants[slot]
                if not cands: continue
                
                date_part = slot.split(" ")[0]
                # 1日2枠制限
                valid = [c for c in cands if daily_counts[c][date_part] < 2]
                
                if valid:
                    # 平準化
                    valid.sort(key=lambda x: (student_counts[x], random.random()))
                    winner = valid[0]
                    final_schedule[slot] = winner
                    student_counts[winner] += 1
                    daily_counts[winner][date_part] += 1
            
            # 結果表示（まだ保存はしない）
            st.success("シフト案を作成しました。問題なければ下のボタンで「確定（履歴に保存）」してください。")
            
            # データフレーム化
            res_list = []
            for slot in current_slots:
                winner = final_schedule.get(slot, None)
                if winner:
                    res_list.append({
                        "日時": slot, 
                        "受講者": winner, 
                        "学期": get_semester(slot)
                    })
            
            if res_list:
                st.session_state["preview_schedule"] = pd.DataFrame(res_list)
                st.table(st.session_state["preview_schedule"])
            else:
                st.warning("マッチング成立数: 0")

    # 確定ボタン
    if "preview_schedule" in st.session_state:
        if st.button("このシフトで確定し、履歴に保存する"):
            save_history(st.session_state["preview_schedule"])
            st.success("履歴シート(History)に保存しました！「データ集計」タブで回数を確認できます。")
            del st.session_state["preview_schedule"] # クリア

# ==========================================
# タブ3: データ集計 (半期ごとの回数)
# ==========================================
with tab3:
    st.header("レッスン回数集計")
    st.caption("Historyシートに保存されたデータを元に集計します。")
    
    df_hist = load_history()
    
    if df_hist.empty:
        st.info("まだ確定された履歴がありません。")
    else:
        # ピボットテーブルで集計（行:氏名、列:学期）
        try:
            pivot = pd.crosstab(df_hist["受講者"], df_hist["学期"], margins=True, margins_name="合計")
            st.dataframe(pivot)
            
            st.markdown("### 詳細履歴")
            st.dataframe(df_hist)
        except:
            st.error("集計エラー。データ形式を確認してください。")
