import streamlit as st
import pandas as pd
import random
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", layout="wide")
st.title("🎹 レッスン日程 自動調整システム")

# 先生が提示する候補日（ここで編集してください）
TEACHER_SLOTS = [
    "10/4(土) 10:00-10:50", "10/4(土) 11:00-11:50", "10/4(土) 13:00-13:50",
    "10/4(土) 14:00-14:50", "10/4(土) 15:00-15:50",
    "10/5(日) 10:00-10:50", "10/5(日) 11:00-11:50", "10/5(日) 13:00-13:50",
    "10/11(土) 10:00-10:50", "10/11(土) 11:00-11:50"
]

# --- データベース接続 (Google Sheets) ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(worksheet="Sheet1", usecols=[0, 1], ttl=0)
        if df.shape[1] < 2 or "氏名" not in df.columns:
            return pd.DataFrame(columns=["氏名", "希望枠"])
        return df.dropna(how="all")
    except Exception:
        return pd.DataFrame(columns=["氏名", "希望枠"])

def save_data(new_df):
    conn.update(worksheet="Sheet1", data=new_df)

# --- メイン画面 ---
df = load_data()

st.header("1. 学生希望入力")
st.caption("自分の名前を入力し、参加できる日時にチェックを入れて「送信」を押してください。")

with st.form("student_form"):
    student_name = st.text_input("氏名 (フルネーム)", placeholder="例: 松村泰佑")
    
    st.write("▼ 可能な枠にチェックを入れてください")
    
    existing_wishes = []
    if not df.empty and student_name in df["氏名"].values:
        row = df[df["氏名"] == student_name].iloc[0]
        if pd.notna(row["希望枠"]):
            existing_wishes = row["希望枠"].split(",")

    selected_slots = []
    cols = st.columns(2)
    for i, slot in enumerate(TEACHER_SLOTS):
        is_checked = slot in existing_wishes
        if cols[i % 2].checkbox(slot, value=is_checked, key=f"chk_{i}"):
            selected_slots.append(slot)
    
    submitted = st.form_submit_button("希望を送信 / 更新")

    if submitted:
        if not student_name:
            st.error("名前を入力してください！")
        else:
            wishes_str = ",".join(selected_slots)
            new_row = {"氏名": student_name, "希望枠": wishes_str}
            df = df[df["氏名"] != student_name]
            new_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            save_data(new_df)
            st.success(f"{student_name}さんの希望を保存しました！")
            st.rerun()

# --- 状況表示 ---
st.markdown("---")
st.subheader("現在の回答状況")
if not df.empty:
    display_df = df.copy()
    display_df["希望枠数"] = display_df["希望枠"].apply(lambda x: len(x.split(",")) if x else 0)
    st.dataframe(display_df[["氏名", "希望枠数"]])
else:
    st.info("まだ回答はありません。")

# --- 自動調整 ---
st.markdown("---")
st.header("2. スケジュール自動調整 (先生用)")

if st.button("シフトを作成する"):
    if df.empty:
        st.error("データがありません。")
    else:
        student_requests = {}
        for index, row in df.iterrows():
            if pd.notna(row["希望枠"]) and row["希望枠"] != "":
                student_requests[row["氏名"]] = row["希望枠"].split(",")
        
        final_schedule = {} 
        student_counts = defaultdict(int)
        student_daily_counts = defaultdict(lambda: defaultdict(int))

        slot_applicants = {slot: [] for slot in TEACHER_SLOTS}
        for name, wishes in student_requests.items():
            for wish in wishes:
                if wish in TEACHER_SLOTS:
                    slot_applicants[wish].append(name)
        
        sorted_slots = sorted(
            [s for s in slot_applicants if slot_applicants[s]],
            key=lambda s: len(slot_applicants[s])
        )

        for slot in sorted_slots:
            candidates = slot_applicants[slot]
            if not candidates: continue
            
            date_part = slot.split(" ")[0] 
            valid_candidates = [s for s in candidates if student_daily_counts[s][date_part] < 2]
            
            if valid_candidates:
                valid_candidates.sort(key=lambda s: (student_counts[s], random.random()))
                winner = valid_candidates[0]
                final_schedule[slot] = winner
                student_counts[winner] += 1
                student_daily_counts[winner][date_part] += 1
            else:
                final_schedule[slot] = "空き (条件不一致)"

        st.success("調整完了！")
        res_data = [{"日時": s, "受講者": final_schedule.get(s, "---")} for s in TEACHER_SLOTS]
        st.table(pd.DataFrame(res_data))
        count_data = [{"氏名": n, "決定回数": c} for n, c in student_counts.items()]
        st.table(pd.DataFrame(count_data))
