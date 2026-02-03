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
st.title("🎹 レッスン日程 自動調整システム v12")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- ユーティリティ関数 ---

def normalize_date_text(text):
    """
    日付と時間を強力に正規化する関数。
    - "9/11" -> "9月11日(木)"
    - "10:00" -> "10:00-10:50" (終了時間がない場合、自動で50分後を追加！)
    - "10:00-11:00" -> "10:00-11:00" (範囲がある場合はそのまま)
    """
    # 1. 全角→半角
    text = unicodedata.normalize('NFKC', text)
    
    # 2. 日付の検出 (M/D, M月D日)
    date_match = re.search(r'(\d{1,2})[\/\-月\.](\d{1,2})', text)
    if not date_match:
        return text # 日付がない行は無視
        
    month, day = int(date_match.group(1)), int(date_match.group(2))
    now = datetime.now()
    year = now.year
    try:
        dt = datetime(year, month, day)
    except ValueError:
        return text
    
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    wk = weekdays[dt.weekday()]
    date_str = f"{month}月{day}日({wk})"
    
    # 3. 時間の検出と補正
    # "10:00" のようなパターンを探す
    time_match = re.search(r'(\d{1,2}:\d{2})', text)
    if time_match:
        start_time_str = time_match.group(1)
        
        # すでに範囲指定があるかチェック ("-" や "~" があるか)
        range_match = re.search(r'(\d{1,2}:\d{2})\s*[\-~〜]\s*(\d{1,2}:\d{2})', text)
        
        if range_match:
            # "10:00-11:00" のように範囲があるなら、区切り文字を "-" に統一して返す
            s_t = range_match.group(1)
            e_t = range_match.group(2)
            return f"{date_str} {s_t}-{e_t}"
        else:
            # ★ここが新機能: 終了時間がない場合、自動で+50分する
            try:
                st_obj = datetime.strptime(start_time_str, "%H:%M")
                et_obj = st_obj + timedelta(minutes=50)
                end_time_str = et_obj.strftime("%H:%M")
                return f"{date_str} {start_time_str}-{end_time_str}"
            except:
                return f"{date_str} {start_time_str}" # 計算失敗時はそのまま
    
    # 時間が書いてない場合は日付だけ返す
    return date_str

def get_semester(date_str):
    match = re.search(r'(\d{1,2})月', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期 (4-8月
