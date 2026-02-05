import streamlit as st
import pandas as pd
import random
import re
import unicodedata
from datetime import datetime, timedelta
from collections import defaultdict
from supabase import create_client, Client

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", page_icon="🎹", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v18")

# --- Supabase接続 ---
try:
    url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except:
    st.error("Secretsの設定が間違っています。[connections.supabase]を確認してください。")
    st.stop()

# --- 関数群 ---

def normalize_date_text(text):
    text = unicodedata.normalize('NFKC', text)
    date_match = re.search(r'(\d{1,2})[\/\-月\.](\d{1,2})', text)
    if not date_match: return text
        
    month, day = int(date_match.group(1)), int(date_match.group(2))
    now = datetime.now()
    year = now.year
    try: dt = datetime(year, month, day)
    except: return text
    
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    wk = weekdays[dt.weekday()]
    date_str = f"{month}月{day}日({wk})"
    
    time_match = re.search(r'(\d{1,2}[:：]\d{2})', text)
    if time_match:
        start_time_str = time_match.group(1).replace("：", ":")
        range_match = re.search(r'(\d{1,2}[:：]\d{2})\s*[\-~〜]\s*(\d{1,2}[:：]\d{2})', text)
        
        if range_match:
            s_t = range_match.group(1).replace("：", ":")
            e_t = range_match.group(2).replace("：", ":")
            return f"{date_str} {s_t}-{e_t}"
        else:
            try:
                st_obj = datetime.strptime(start_time_str, "%H:%M")
                et_obj = st_obj + timedelta(minutes=50)
                end_time_str = et_obj.strftime("%H:%M")
                return f"{date_str} {start_time_str}-{end_time_str}"
            except:
                return f"{date_str} {start_time_str}"
    
    return date_str

def get_semester(date_str):
    match = re.search(r'(\d{1,2})月', date_str)
    if match:
        if 4 <= int(match.group(1)) <= 8: return "前期"
        else: return "後期"
    return "不明"

def sort_slots(slot_list):
    def parse_key(s):
        try:
            # 日付と時間を数値化してソートキーにする
            match = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2}):(\d{2})', s)
            if match:
                mo, d, h, m = map(int, match.groups())
                return (1 if mo <= 3 else 0, mo, d, h, m)
            return (99, 99, 99, 99, 99)
        except: return (99, 99, 99, 99, 99)
    return sorted(slot_list, key=parse_key)

def group_continuous_slots(sorted_slots):
    """
    連続した枠をまとめて表示するための関数
    例: 10:00-10:50, 10:50-11:40 -> "10:00〜11:40 (2枠)"
    """
    if not sorted_slots: return []
    
    # 日付ごとに分ける
    grouped_by_date = defaultdict(list)
    for s in sorted_slots:
        d_part = s.split(" ")[0]
        t_part = s.split(" ")[1] if " " in s else ""
        grouped_by_date[d_part].append(t_part)
        
    summary_list = []
    
    for date_key, times in grouped_by_date.items():
        # 時間順にソート済み前提
        if not times: continue
        
        current_start
