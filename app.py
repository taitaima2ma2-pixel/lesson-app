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
    col_edit, col_tool = st.columns([1,
