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
    name_list = sorted(list(set(name_list)))
    save_data("Students", pd.DataFrame({"氏名": name_list}))

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用", "📅 先生用 (日程管理)", "📊 データ集計"])

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

            slots_by_date = defaultdict(list)
            for slot in current_slots:
                date_match = re.match(r'(.*?\(.\))', slot)
                if date_match: date_key = date_match.group(1)
                else: date_key = slot.split(" ")[0]
                slots_by_date[date_key].append(slot)

            with st.form("student_form"):
                final_selected_slots = []
                for date_key, slots_in_date in slots_by_date.items():
                    with st.expander(f"📅 {date_key}", expanded=True):
                        all_checked_now = all(s in existing_wishes for s in slots_in_date)
                        all_day_ok = st.checkbox(f"🙆‍♂️ {date_key} は何時でもOK (全選択)", value=all_checked_now, key=f"all_{date_key}")
                        
                        cols = st.columns(2)
                        for i, slot in enumerate(slots_in_date):
                            is_checked = True if all_day_ok else (slot in existing_wishes)
                            time_part = slot.replace(date_key, "").strip()
                            if cols[i % 2].checkbox(time_part, value=is_checked, key=f"chk_{slot}"):
                                final_selected_slots.append(slot)

                st.markdown("---")
                if st.form_submit_button("希望を送信 / 更新する", type="primary"):
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
    
    # 名簿管理
    with st.expander("👥 学生名簿管理", expanded=False):
        current_students = load_students()
        new_std_text = st.text_area("学生リスト", value="\n".join(current_students), height=100)
        if st.button("名簿保存"):
            save_students([l.strip() for l in new_std_text.split('\n') if l.strip()])
            st.success("更新しました")
            st.rerun()
    
    st.markdown("---")
    
    # ★変更点1: 現在のリストを常に表示する
    current_slots = load_slots()
    st.subheader(f"📅 登録済み日程 ({len(current_slots)}枠)")
    
    if current_slots:
        # 見やすく表示
        df_slots = pd.DataFrame({"日時": current_slots})
        st.dataframe(df_slots, use_container_width=True, hide_index=True)
    else:
        st.info("現在、登録されている枠はありません。")

    # ★変更点2: 編集エリアを「リストの下」に配置し、常に開いた状態にする
    st.markdown("---")
    st.write("#### ✏️ 日程の編集・追加")
    
    # A. 魔法の一括追加ツール
    with st.container():
        st.caption("【方法A】自動作成ツール (日付と時間を入れるだけ)")
        c1, c2, c3 = st.columns(3)
        gen_date = c1.text_input("日付 (例: 9/11)", value="9/11")
        gen_start = c2.text_input("開始 (例: 10:00)", value="10:00")
        gen_end = c3.text_input("終了 (例: 13:00)", value="13:00")

        if st.button("プランを計算"):
            try:
                norm_date = normalize_date_text(gen_date).split(" ")[0]
                dummy = datetime(2000, 1, 1)
                t_s = datetime.strptime(gen_start, "%H:%M")
                t_e = datetime.strptime(gen_end, "%H:%M")
                
                plan_a = []
                curr = datetime.combine(dummy, t_s.time())
                limit = datetime.combine(dummy, t_e.time())
                while curr + timedelta(minutes=50) <= limit:
                    nxt = curr + timedelta(minutes=50)
                    plan_a.append(f"{norm_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                    curr = nxt
                
                plan_b = []
                curr = datetime.combine(dummy, t_s.time())
                while curr < limit:
                    nxt = curr + timedelta(minutes=50)
                    plan_b.append(f"{norm_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                    curr = nxt
                
                st.session_state["p_a"], st.session_state["p_b"] = plan_a, plan_b
            except: st.error("時間を正しく入力してください")

        if "p_a" in st.session_state:
            ca, cb = st.columns(2)
            with ca:
                st.markdown(f"**🅰️ 時間内 ({len(st.session_state['p_a'])}枠)**")
                for s in st.session_state['p_a']: st.caption(s)
                if st.button("🅰️ 追加保存"):
                    save_slots(current_slots + st.session_state['p_a'])
                    del st.session_state['p_a'], st.session_state['p_b']
                    st.rerun()
            with cb:
                st.markdown(f"**🅱️ 使い切り ({len(st.session_state['p_b'])}枠)**")
                for s in st.session_state['p_b']: st.caption(s)
                if st.button("🅱️ 追加保存"):
                    save_slots(current_slots + st.session_state['p_b'])
                    del st.session_state['p_a'], st.session_state['p_b']
                    st.rerun()

    st.markdown("---")

    # B. 手動編集リスト (expanded=True で常に開く)
    with st.expander("【方法B】リストを直接編集する (コピペ用)", expanded=True):
        st.caption("ここを書き換えて「更新」を押すと、上の「登録済み日程」が書き換わります。")
        edited_text = st.text_area("編集エリア", value="\n".join(current_slots), height=200)
        
        if st.button("この内容で上書き保存する", type="primary"):
            lines = [l.strip() for l in edited_text.split('\n') if l.strip()]
            save_slots(lines)
            st.success("保存しました！")
            st.rerun()

    st.markdown("---")
    st.subheader("🤖 シフト自動作成")
    
    if st.button("シフトを作成する"):
        current_slots = load_slots()
        df_req = load_requests()
        df_hist = load_history()
        
        if df_req.empty or not current_slots:
            st.error("データ不足")
        else:
            req_dict = {}
            for _, row in df_req.iterrows():
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    req_dict[row["氏名"]] = row["希望枠"].split(",")

            slot_applicants = {s: [] for s in current_slots}
            for name, wishes in req_dict.items():
                for w in wishes:
                    if w in current_slots: slot_applicants[w].append(name)
            
            final_schedule = {}
            current_batch_counts = defaultdict(int)
            daily_counts = defaultdict(lambda: defaultdict(int))
            sorted_slots_process = sort_slots(current_slots)

            for slot in sorted_slots_process:
                cands = slot_applicants[slot]
                if not cands: continue

                semester = get_semester(slot)
                # date_part抽出 (簡易)
                if "(" in slot: date_part = slot.split("(")[0]
                else: date_part = slot.split(" ")[0]

                scored_cands = []
                for student in cands:
                    if daily_counts[student][date_part] >= 2: continue
                    past_count = len(df_hist[ (df_hist["受講者"]==student) & (df_hist["学期"]==semester) ])
                    total_count = past_count + current_batch_counts[student]
                    continuity_bonus = 0
                    if daily_counts[student][date_part] == 1: continuity_bonus = -5
                    score = total_count + continuity_bonus
                    scored_cands.append( (score, random.random(), student) )
                
                if scored_cands:
                    scored_cands.sort()
                    winner = scored_cands[0][2]
                    final_schedule[slot] = winner
                    current_batch_counts[winner] += 1
                    daily_counts[winner][date_part] += 1
            
            res_list = []
            for slot in sort_slots(current_slots):
                winner = final_schedule.get(slot, "")
                status = winner if winner else "❌ (成立なし)"
                res_list.append({"日時": slot, "受講者": status, "学期": get_semester(slot)})
            
            st.session_state["preview"] = pd.DataFrame(res_list)
            st.table(st.session_state["preview"])

    if "preview" in st.session_state:
        if st.button("確定して履歴に保存"):
            to_save = st.session_state["preview"][ st.session_state["preview"]["受講者"] != "❌ (成立なし)" ]
            save_history(to_save)
            st.success("保存しました")
            del st.session_state["preview"]

# ==========================================
# タブ3: 集計
# ==========================================
with tab3:
    st.header("集計")
    df_hist = load_history()
    if not df_hist.empty:
        pivot = pd.crosstab(df_hist["受講者"], df_hist["学期"], margins=True, margins_name="合計")
        st.dataframe(pivot)
    else: st.info("データなし")
