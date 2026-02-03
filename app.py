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
st.title("🎹 レッスン日程 自動調整システム v10")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- ユーティリティ関数 ---

# 全角数字などを半角に、日付表記を統一する魔法の関数
def normalize_date_text(text):
    # 1. 全角→半角正規化
    text = unicodedata.normalize('NFKC', text)
    
    # 2. 日付っぽい部分を探す (M/D, M月D日, M-Dなど)
    # 年は指定がない場合、現在に近い未来の日付を推測する
    match = re.search(r'(\d{1,2})[\/\-月\.](\d{1,2})', text)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        year = now.year
        
        # もし「1月」の予定を「12月」に入力しているなら来年扱いにする等
        # ここではシンプルに「今日より過去なら来年」とする簡易ロジック
        try:
            dt = datetime(year, month, day)
            if dt < datetime(year, 1, 1): # ありえないが念のため
                pass 
        except ValueError:
            return text # 日付変換できない場合はそのまま返す

        # 曜日を計算
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        wk = weekdays[dt.weekday()]
        
        # 新しいフォーマット: "9月11日(土)"
        date_str = f"{month}月{day}日({wk})"
        
        # 元のテキストの日付部分を置換、あるいは日付部分のみ抽出して時間をくっつける
        # ここでは「日付 + 時間」の形式であることを前提に、日付部分を再構築する
        # 時間部分を探す (10:00-11:00)
        time_match = re.search(r'(\d{1,2}:\d{2}.*)', text)
        if time_match:
            return f"{date_str} {time_match.group(1)}"
        else:
            return date_str # 時間がない場合は日付だけ
            
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

# --- DB操作関数 ---
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
    # 保存時に正規化を実行！
    normalized_list = [normalize_date_text(s) for s in slot_list]
    # 重複排除 & ソート
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
    name_list = sorted(list(set(name_list)))
    save_data("Students", pd.DataFrame({"氏名": name_list}))

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用: 希望提出", "📅 先生用: 管理・登録", "📊 データ集計"])

# ==========================================
# タブ1: 学生用
# ==========================================
with tab1:
    st.header("希望スケジュールの入力")
    raw_slots = load_slots()
    student_list = load_students()
    
    if not raw_slots:
        st.warning("現在、募集中のレッスン枠はありません。")
    else:
        current_slots = sort_slots(raw_slots)
        df_req = load_requests()
        
        # 名前選択
        student_name = ""
        if not student_list:
            st.error("⚠️ 名簿が空です。先生に連絡してください。")
        else:
            selected_val = st.selectbox("氏名を選択", ["(名前を選択してください)"] + student_list)
            if selected_val != "(名前を選択してください)":
                student_name = selected_val

        if student_name:
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    existing_wishes = row["希望枠"].split(",")
            
            st.info(f"ログイン中: **{student_name}** さん (現在の希望数: {len(existing_wishes)})")
            st.write("▼ 参加できる日時を選んでください")

            # 日付ごとのグループ化
            slots_by_date = defaultdict(list)
            for slot in current_slots:
                # "9月11日(土)" の部分だけ抽出してキーにする
                date_match = re.match(r'(.*?\(.\))', slot)
                if date_match:
                    date_key = date_match.group(1)
                else:
                    date_key = slot.split(" ")[0] # フォールバック
                slots_by_date[date_key].append(slot)

            with st.form("student_form"):
                final_selected_slots = []
                
                for date_key, slots_in_date in slots_by_date.items():
                    with st.expander(f"📅 {date_key}", expanded=True):
                        # ★機能追加: この日はいつでも可
                        # まず、この日のスロットが全て既存希望に含まれているかチェック
                        all_checked_now = all(s in existing_wishes for s in slots_in_date)
                        
                        # 全選択チェックボックス
                        all_day_ok = st.checkbox(f"🙆‍♂️ {date_key} は何時でもOK (全選択)", value=all_checked_now, key=f"all_{date_key}")
                        
                        st.caption("個別に選択する場合は以下をチェック:")
                        cols = st.columns(2)
                        for i, slot in enumerate(slots_in_date):
                            # 全選択がONなら、個別の表示もONに見せかける(保存時は全選択の値を優先)
                            # ここではUI上の整合性のため、all_day_okならTrue、そうでなければ既存値を参照
                            is_checked = True if all_day_ok else (slot in existing_wishes)
                            
                            # 時間部分だけ表示
                            time_part = slot.replace(date_key, "").strip()
                            
                            # ユーザーが操作するチェックボックス
                            user_checked = cols[i % 2].checkbox(time_part, value=is_checked, key=f"chk_{slot}")
                            
                            if user_checked:
                                final_selected_slots.append(slot)

                st.markdown("---")
                if st.form_submit_button("希望を送信 / 更新する", type="primary"):
                    # 重複除去
                    final_selected_slots = sorted(list(set(final_selected_slots)), key=lambda s: current_slots.index(s) if s in current_slots else 999)
                    wishes_str = ",".join(final_selected_slots)
                    new_row = {"氏名": student_name, "希望枠": wishes_str}
                    
                    df_req = df_req[df_req["氏名"] != student_name]
                    new_df = pd.concat([df_req, pd.DataFrame([new_row])], ignore_index=True)
                    save_requests(new_df)
                    st.success("✅ 保存しました！")
                    st.rerun()

# ==========================================
# タブ2: 先生用
# ==========================================
with tab2:
    st.header("管理者メニュー")

    with st.expander("👥 学生名簿管理", expanded=False):
        current_students = load_students()
        new_std_text = st.text_area("学生リスト (改行区切り)", value="\n".join(current_students), height=150)
        if st.button("名簿保存"):
            save_students([l.strip() for l in new_std_text.split('\n') if l.strip()])
            st.success("更新しました")
            st.rerun()

    st.markdown("---")
    
    # リスト編集
    current_slots = load_slots()
    with st.expander("📝 候補日の手動編集 (表記は自動統一されます)"):
        edited_text = st.text_area("編集エリア", value="\n".join(current_slots), height=200)
        if st.button("更新保存"):
            # ここで normalize_date_text が走る
            lines = [l.strip() for l in edited_text.split('\n') if l.strip()]
