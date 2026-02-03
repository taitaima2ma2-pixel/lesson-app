import streamlit as st
import pandas as pd
import random
import re
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v3")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 関数群 ---
def load_slots():
    try:
        df = conn.read(worksheet="Slots", usecols=[0], ttl=0)
        if df.empty or df.columns[0] != "候補日時": return []
        return df["候補日時"].dropna().tolist()
    except: return []

def save_slots(slot_list):
    df = pd.DataFrame({"候補日時": slot_list})
    conn.update(worksheet="Slots", data=df)

def load_requests():
    try:
        df = conn.read(worksheet="Requests", usecols=[0, 1], ttl=0)
        if df.shape[1] < 2: return pd.DataFrame(columns=["氏名", "希望枠"])
        return df.dropna(how="all")
    except: return pd.DataFrame(columns=["氏名", "希望枠"])

def save_requests(new_df):
    conn.update(worksheet="Requests", data=new_df)

def load_history():
    try:
        df = conn.read(worksheet="History", usecols=[0, 1, 2], ttl=0)
        if df.shape[1] < 3: return pd.DataFrame(columns=["日時", "受講者", "学期"])
        return df
    except: return pd.DataFrame(columns=["日時", "受講者", "学期"])

def save_history(new_records_df):
    old_df = load_history()
    if old_df.empty: updated_df = new_records_df
    else: updated_df = pd.concat([old_df, new_records_df], ignore_index=True)
    conn.update(worksheet="History", data=updated_df)

def get_semester(date_str):
    match = re.search(r'(\d+)/', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期 (4-8月)"
        else: return "後期 (9-2月)"
    return "不明"

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用: 希望提出", "📅 先生用: 日程調整・管理", "📊 データ集計"])

# ----------------------------------------
# タブ1: 学生用
# ----------------------------------------
with tab1:
    st.header("希望スケジュールの入力")
    current_slots = load_slots()
    
    if not current_slots:
        st.warning("現在、募集中のレッスン枠はありません。")
    else:
        df_req = load_requests()
        with st.form("student_form"):
            student_name = st.text_input("氏名 (フルネーム)", placeholder="例: 松村泰佑")
            st.write("▼ 可能な日時にチェックを入れてください")
            
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]): existing_wishes = row["希望枠"].split(",")
            
            selected = []
            cols = st.columns(2)
            for i, slot in enumerate(current_slots):
                is_checked = slot in existing_wishes
                if cols[i % 2].checkbox(slot, value=is_checked, key=f"s_{i}"):
                    selected.append(slot)
            
            if st.form_submit_button("送信 / 更新"):
                if not student_name: st.error("名前を入れてください")
                else:
                    wishes_str = ",".join(selected)
                    new_row = {"氏名": student_name, "希望枠": wishes_str}
                    df_req = df_req[df_req["氏名"] != student_name]
                    new_df = pd.concat([df_req, pd.DataFrame([new_row])], ignore_index=True)
                    save_requests(new_df)
                    st.success(f"{student_name}さんの希望を保存しました！")
                    st.rerun()

# ----------------------------------------
# タブ2: 先生用 (機能追加版)
# ----------------------------------------
with tab2:
    st.header("管理者メニュー")

    # --- 左カラム: 編集エディタ ---
    col_edit, col_tool = st.columns([1, 1])
    
    with col_edit:
        st.subheader("📝 候補日リストの編集")
        current_slots = load_slots()
        default_text = "\n".join(current_slots)
        new_text = st.text_area("ここを直接編集して保存できます", value=default_text, height=400)
        
        if st.button("リストを更新して保存"):
            new_list = [line.strip() for line in new_text.split('\n') if line.strip()]
            save_slots(new_list)
            st.success("保存しました！")
            st.rerun()

    # --- 右カラム: 自動生成ツール ---
    with col_tool:
        st.info("💡 **一括追加ツール**\n\n日付と時間を選ぶと、自動で「50分枠」を作ってリストに追加します。")
        with st.form("generator"):
            gen_date = st.text_input("日付 (例: 10/4(土))")
            start_hour = st.number_input("開始時", 9, 21, 10)
            end_hour = st.number_input("終了時 (この時間まで作成)", 10, 22, 18)
            
            if st.form_submit_button("この条件で枠を追加"):
                added_slots = []
                # 開始時から終了時までループ
                for h in range(start_hour, end_hour):
                    # 50分枠を作成 (例: 10:00-10:50)
                    slot_str = f"{gen_date} {h}:00-{h}:50"
                    added_slots.append(slot_str)
                
                # 既存リストに追加
                current_list = [line.strip() for line in new_text.split('\n') if line.strip()]
                updated_list = current_list + added_slots
                save_slots(updated_list)
                st.success(f"{len(added_slots)}個の枠を追加しました！左のリストを確認して「更新して保存」は不要です(自動保存済)。")
                st.rerun()

    st.markdown("---")
    st.subheader("シフト自動作成")
    if st.button("現在の希望でシフトを組む"):
        current_slots = load_slots()
        df_req = load_requests()
        
        if df_req.empty or not current_slots:
            st.error("データ不足です")
        else:
            # ロジック
            req_dict = {}
            for _, row in df_req.iterrows():
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    req_dict[row["氏名"]] = row["希望枠"].split(",")
            
            final_schedule = {}
            student_counts = defaultdict(int)
            daily_counts = defaultdict(lambda: defaultdict(int))
            slot_applicants = {s: [] for s in current_slots}
            
            for name, wishes in req_dict.items():
                for w in wishes:
                    if w in current_slots: slot_applicants[w].append(name)
            
            sorted_slots = sorted(
                [s for s in current_slots if slot_applicants[s]],
                key=lambda s: len(slot_applicants[s])
            )
            
            for slot in sorted_slots:
                cands = slot_applicants[slot]
                if not cands: continue
                
                # 日付判定 (スペース区切りの1つ目)
                date_part = slot.split(" ")[0]
                valid = [c for c in cands if daily_counts[c][date_part] < 2]
                
                if valid:
                    valid.sort(key=lambda x: (student_counts[x], random.random()))
                    winner = valid[0]
                    final_schedule[slot] = winner
                    student_counts[winner] += 1
                    daily_counts[winner][date_part] += 1
            
            st.success("シフト案を作成しました。")
            res_list = []
            for slot in current_slots:
                winner = final_schedule.get(slot, None)
                if winner:
                    res_list.append({"日時": slot, "受講者": winner, "学期": get_semester(slot)})
            
            if res_list:
                st.session_state["preview_schedule"] = pd.DataFrame(res_list)
                st.table(st.session_state["preview_schedule"])
            else: st.warning("マッチング成立数: 0")

    if "preview_schedule" in st.session_state:
        if st.button("このシフトで確定し、履歴に保存する"):
            save_history(st.session_state["preview_schedule"])
            st.success("履歴に保存しました！")
            del st.session_state["preview_schedule"]

# ----------------------------------------
# タブ3: 集計
# ----------------------------------------
with tab3:
    st.header("レッスン回数集計")
    df_hist = load_history()
    if df_hist.empty: st.info("履歴なし")
    else:
        try:
            pivot = pd.crosstab(df_hist["受講者"], df_hist["学期"], margins=True, margins_name="合計")
            st.dataframe(pivot)
            st.write("詳細履歴", df_hist)
        except: st.error("集計エラー")
