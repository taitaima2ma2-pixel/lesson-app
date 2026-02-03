import streamlit as st
import pandas as pd
import random
import re
import unicodedata
from datetime import datetime, timedelta
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", page_icon="🎹", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v11")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 関数群 ---

def normalize_date_text(text):
    # 全角数字を半角に
    text = unicodedata.normalize('NFKC', text)
    # 日付(M/D, M月D日)を探す
    match = re.search(r'(\d{1,2})[\/\-月\.](\d{1,2})', text)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        year = now.year
        try:
            dt = datetime(year, month, day)
        except ValueError:
            return text
        
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        wk = weekdays[dt.weekday()]
        date_str = f"{month}月{day}日({wk})"
        
        # 時間があればくっつける
        time_match = re.search(r'(\d{1,2}:\d{2}.*)', text)
        if time_match:
            return f"{date_str} {time_match.group(1)}"
        else:
            return date_str
            
    return text

def get_semester(date_str):
    match = re.search(r'(\d{1,2})月', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期 (4-8月)"
        else: return "後期 (9-2月)"
    return "不明"

def sort_slots(slot_list):
    def parse_key(s):
        try:
            match = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2}):(\d{2})', s)
            if match:
                mo, d, h, m = map(int, match.groups())
                year_offset = 1 if mo <= 3 else 0
                return (year_offset, mo, d, h, m)
            return (99, 99, 99, 99, 99)
        except: return (99, 99, 99, 99, 99)
    return sorted(slot_list, key=parse_key)

# --- DB操作 ---
def load_data(sheet_name, cols):
    try:
        df = conn.read(worksheet=sheet_name, usecols=list(range(cols)), ttl=0)
        return df.dropna(how="all")
    except: return pd.DataFrame()

def save_data(sheet_name, df):
    conn.update(worksheet=sheet_name, data=df)

def load_slots():
    df = load_data("Slots", 1)
    if df.empty or df.columns[0] != "候補日時": return []
    return df["候補日時"].dropna().tolist()

def save_slots(slot_list):
    # 正規化とソートをして保存
    normalized_list = [normalize_date_text(s) for s in slot_list]
    normalized_list = sorted(list(set(normalized_list)), key=lambda s: sort_slots([s])[0])
    save_data("Slots", pd.DataFrame({"候補日時": normalized_list}))

def load_requests():
    df = load_data("Requests", 2)
    if df.shape[1] < 2: return pd.DataFrame(columns=["氏名", "希望枠"])
    return df

def save_requests(new_df):
    save_data("Requests", new_df)

def load_history():
    df = load_data("History", 3)
    if df.shape[1] < 3: return pd.DataFrame(columns=["日時", "受講者", "学期"])
    return df

def save_history(new_df):
    old_df = load_history()
    if old_df.empty: updated = new_df
    else: updated = pd.concat([old_df, new_df], ignore_index=True)
    save_data("History", updated)

def load_students():
    df = load_data("Students", 1)
    if df.empty or df.columns[0] != "氏名": return []
    return df["氏名"].dropna().tolist()

def save_students(name_list):
    name_list = sorted(list(
