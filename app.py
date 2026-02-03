import streamlit as st
import pandas as pd
import random
import re
from datetime import datetime, timedelta, time
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v4")

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
# タブ2: 先生用 (v4: 連続枠生成機能付き)
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

    # --- 右カラム: 自動生成ツール (改良版) ---
    with col_tool:
        st.info("💡 **一括追加ツール (改)**\n\n50分レッスンを**間隔を空けずに連続して**作成します。\n(例: 10:00-10:50, 10:50-11:40...)")
        
        with st.form("generator"):
            gen_date_str = st.text_input("日付 (例: 10/4(土))", value="10/4(土)")
            
            # 10分刻みの時間リストを作成 (8:00〜22:00)
            time_options = []
            for h in range(8, 23):
                for m in range(0, 60, 10):
                    time_options.append(time(h, m))
            
            # デフォルト値の設定 (10:00開始, 18:00終了)
            def_start = time(10, 0)
            def_end = time(18, 0)
            try:
                idx_start = time_options.index(def_start)
                idx_end = time_options.index(def_end)
            except:
                idx_start, idx_end = 0, len(time_options)-1

            col_t1, col_t2 = st.columns(2)
            start_t = col_t1.selectbox("開始時間", time_options, index=idx_start, format_func=lambda t: t.strftime("%H:%M"))
            end_t = col_t2.selectbox("終了時間 (この時間まで)", time_options, index=idx_end, format_func=lambda t: t.strftime("%H:%M"))
            
            if st.form_submit_button("この条件で枠を追加"):
                added_slots = []
                
                # 計算用にdatetimeオブジェクト化 (日付部分はダミー)
                dummy_date = datetime(2000, 1, 1)
                curr_dt = datetime.combine(dummy_date, start_t)
                limit_dt = datetime.combine(dummy_date, end_t)
                
                # 終了時間を超えない限りループ
                while curr_dt + timedelta(minutes=50) <= limit_dt:
                    next_dt = curr_dt + timedelta(minutes=50)
                    
                    s_str = curr_dt.strftime("%H:%M")
                    e_str = next_dt.strftime("%H:%M")
                    
                    slot_str = f"{gen_date_str} {s_str}-{e_str}"
                    added_slots.append(slot_str)
                    
                    # 休憩なしなので、次は「今の終了時間」からスタート
                    curr_dt = next_dt
                
                # 保存処理
                if added_slots:
                    current_list = [line.strip() for line in new_text.split('\n') if line.strip()]
                    updated_list = current_list + added_slots
                    save_slots(updated_list)
                    st.success(f"{len(added_slots)}個の枠を追加しました！")
                    st.rerun()
                else:
                    st.warning("枠が作成されませんでした。終了時間を開始時間より遅くしてください。")

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
                if not
