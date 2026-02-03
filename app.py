import streamlit as st
import pandas as pd
import random
import re
from datetime import datetime, timedelta
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v5")

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

# --- ソート用関数 (日付順に並べる) ---
def sort_slots(slot_list):
    def parse_key(s):
        # "10/4(土) 09:30-10:20" のような文字列から数字を抜き出して比較用にする
        # 抜き出し失敗時は最後尾へ
        try:
            # 月、日、開始時、開始分 を抽出
            match = re.search(r'(\d+)/(\d+).*?(\d+):(\d+)', s)
            if match:
                mo, d, h, m = map(int, match.groups())
                # 年またぎ対応 (簡易): 1,2,3月は来年扱いとして大きな数字を足す
                year_offset = 1 if mo <= 3 else 0
                return (year_offset, mo, d, h, m)
            return (99, 99, 99, 99, 99)
        except:
            return (99, 99, 99, 99, 99)
            
    return sorted(slot_list, key=parse_key)

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用: 希望提出", "📅 先生用: 日程調整・管理", "📊 データ集計"])

# ----------------------------------------
# タブ1: 学生用
# ----------------------------------------
with tab1:
    st.header("希望スケジュールの入力")
    raw_slots = load_slots()
    
    if not raw_slots:
        st.warning("現在、募集中のレッスン枠はありません。")
    else:
        # ★ここで自動ソート (見やすさ改善)
        current_slots = sort_slots(raw_slots)
        
        df_req = load_requests()
        with st.form("student_form"):
            student_name = st.text_input("氏名 (フルネーム)", placeholder="例: 松村泰佑")
            st.write("▼ 可能な日時にチェックを入れてください (日付順)")
            
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
# タブ2: 先生用
# ----------------------------------------
with tab2:
    st.header("管理者メニュー")

    col_edit, col_tool = st.columns([1, 1])
    
    # --- 左: テキスト編集 ---
    with col_edit:
        st.subheader("📝 候補日リストの編集")
        raw_slots = load_slots()
        # ここでもソートして表示すると管理しやすい
        sorted_slots = sort_slots(raw_slots)
        default_text = "\n".join(sorted_slots)
        
        new_text = st.text_area("直接編集エリア", value=default_text, height=400)
        
        if st.button("リストを更新して保存"):
            new_list = [line.strip() for line in new_text.split('\n') if line.strip()]
            save_slots(new_list)
            st.success("保存しました！タブ1で確認してください。")
            st.rerun()

    # --- 右: シンプル一括追加 (直接入力版) ---
    with col_tool:
        st.info("💡 **一括追加ツール**\n\n50分枠を連続作成します。時間は手入力してください。")
        
        with st.form("generator"):
            gen_date_str = st.text_input("日付 (例: 10/4(土))", value="10/4(土)")
            
            # ドロップダウンをやめて直接入力に変更
            c1, c2 = st.columns(2)
            start_str = c1.text_input("開始時間 (例: 09:30)", value="10:00")
            end_str = c2.text_input("終了時間 (例: 17:00)", value="12:00")
            
            if st.form_submit_button("枠を追加"):
                added_slots = []
                try:
                    # 時間文字列を解析
                    dummy_date = datetime(2000, 1, 1)
                    t_start = datetime.strptime(start_str, "%H:%M")
                    t_end = datetime.strptime(end_str, "%H:%M")
                    
                    curr_dt = datetime.combine(dummy_date, t_start.time())
                    limit_dt = datetime.combine(dummy_date, t_end.time())
                    
                    # 生成ループ
                    while curr_dt + timedelta(minutes=50) <= limit_dt:
                        next_dt = curr_dt + timedelta(minutes=50)
                        s_txt = curr_dt.strftime("%H:%M")
                        e_txt = next_dt.strftime("%H:%M")
                        
                        slot_str = f"{gen_date_str} {s_txt}-{e_txt}"
                        added_slots.append(slot_str)
                        curr_dt = next_dt
                    
                    if added_slots:
                        # 既存リストと合体して保存
                        current_list = [line.strip() for line in new_text.split('\n') if line.strip()]
                        updated_list = current_list + added_slots
                        # 保存時に自動ソートしてあげる
                        updated_list = sort_slots(updated_list)
                        save_slots(updated_list)
                        st.success(f"{len(added_slots)}個の枠を追加しました！")
                        st.rerun()
                    else:
                        st.warning("枠が作成されませんでした。終了時間を開始時間より後にしてください。")
                except ValueError:
                    st.error("時間の形式が正しくありません。「09:30」のように半角で入力してください。")

    st.markdown("---")
    st.subheader("シフト自動作成")
    if st.button("現在の希望でシフトを組む"):
        current_slots = load_slots()
        # シフト作成時もソートしておくと処理順が綺麗になる
        current_slots = sort_slots(current_slots)
        
        df_req = load_requests()
        
        if df_req.empty or not current_slots:
            st.error("データ不足です")
        else:
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
