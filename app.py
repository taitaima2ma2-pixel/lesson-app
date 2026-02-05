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
st.title("🎹 レッスン日程 自動調整システム v22")

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
            match = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2}):(\d{2})', s)
            if match:
                mo, d, h, m = map(int, match.groups())
                return (1 if mo <= 3 else 0, mo, d, h, m)
            return (99, 99, 99, 99, 99)
        except: return (99, 99, 99, 99, 99)
    return sorted(slot_list, key=parse_key)

def group_continuous_slots(sorted_slots):
    if not sorted_slots: return []
    grouped_by_date = defaultdict(list)
    for s in sorted_slots:
        d_part = s.split(" ")[0]
        t_part = s.split(" ")[1] if " " in s else ""
        grouped_by_date[d_part].append(t_part)
    summary_list = []
    for date_key, times in grouped_by_date.items():
        if not times: continue
        current_start, current_end = None, None
        count = 0
        def parse_range(t_str):
            try: return t_str.split("-")
            except: return None, None
        for t in times:
            s, e = parse_range(t)
            if not s: continue 
            if current_start is None:
                current_start, current_end = s, e
                count = 1
            else:
                if current_end == s:
                    current_end = e
                    count += 1
                else:
                    summary_list.append(f"{date_key} {current_start}〜{current_end} ({count}枠)")
                    current_start, current_end = s, e
                    count = 1
        if current_start:
            summary_list.append(f"{date_key} {current_start}〜{current_end} ({count}枠)")
    return summary_list

# --- DB操作 (Supabase) ---

def load_slots():
    response = supabase.table("slots").select("date_text").execute()
    return [item['date_text'] for item in response.data]

def save_slots(slot_list):
    normalized_list = [normalize_date_text(s) for s in slot_list]
    unique_list = sorted(list(set(normalized_list)), key=lambda s: sort_slots([s])[0])
    supabase.table("slots").delete().neq("id", 0).execute() 
    if unique_list:
        data = [{"date_text": s} for s in unique_list]
        supabase.table("slots").insert(data).execute()

def load_requests():
    response = supabase.table("requests").select("*").execute()
    if not response.data: return pd.DataFrame(columns=["氏名", "希望枠"])
    df = pd.DataFrame(response.data)
    return df.rename(columns={"student_name": "氏名", "wishes": "希望枠"})

def save_requests_row(name, wishes_str):
    data = {"student_name": name, "wishes": wishes_str}
    supabase.table("requests").upsert(data, on_conflict="student_name").execute()

def load_history():
    response = supabase.table("history").select("*").execute()
    if not response.data: return pd.DataFrame(columns=["日時", "受講者", "学期"])
    df = pd.DataFrame(response.data)
    return df.rename(columns={"date_text": "日時", "student_name": "受講者", "semester": "学期"})

def save_history_new(df_new):
    if df_new.empty: return
    data = []
    for _, row in df_new.iterrows():
        data.append({
            "date_text": row["日時"],
            "student_name": row["受講者"],
            "semester": row["学期"]
        })
    supabase.table("history").insert(data).execute()

def load_students():
    response = supabase.table("students").select("name").execute()
    return [item['name'] for item in response.data]

def save_students(name_list):
    name_list = sorted(list(set(name_list)))
    supabase.table("students").delete().neq("id", 0).execute()
    if name_list:
        data = [{"name": n} for n in name_list]
        supabase.table("students").insert(data).execute()

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用", "📅 先生用 (登録・管理)", "📊 データ集計"])

# ==========================================
# タブ1: 学生用
# ==========================================
with tab1:
    st.header("レッスン希望の提出")
    raw_slots = load_slots()
    student_list = load_students()
    
    if not raw_slots:
        st.warning("現在、募集中のレッスン枠はありません。")
    else:
        current_slots = sort_slots(raw_slots)
        df_req = load_requests()
        
        student_name = ""
        if not student_list:
            st.error("名簿が登録されていません。")
        else:
            val = st.selectbox("氏名を選択", ["(選択してください)"] + student_list)
            if val != "(選択してください)": student_name = val

        if student_name:
            # ★新機能: 自分の確定スケジュール確認
            st.markdown("---")
            with st.expander("📅 あなたの確定済みレッスンを確認する"):
                df_h = load_history()
                if not df_h.empty:
                    # 今日の日付以降のレッスンを表示
                    today_str = datetime.now().strftime("%m月%d日") # 簡易比較
                    my_lessons = df_h[df_h["受講者"] == student_name]
                    if not my_lessons.empty:
                        # 日付順ソート
                        my_lessons["sort_key"] = my_lessons["日時"].apply(lambda x: sort_slots([x])[0])
                        my_lessons = my_lessons.sort_values("sort_key")
                        
                        for _, row in my_lessons.iterrows():
                            st.success(f"✅ {row['日時']}")
                    else:
                        st.info("確定したレッスンはまだありません。")
                else:
                    st.info("履歴データがありません。")

            st.markdown("---")
            st.write("### 📝 希望日時の登録")
            
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    existing_wishes = row["希望枠"].split(",")
            
            slots_by_date = defaultdict(list)
            for slot in current_slots:
                d_key = slot.split(" ")[0]
                slots_by_date[d_key].append(slot)

            with st.form("student_form"):
                final_selected = []
                for d_key, slots in slots_by_date.items():
                    with st.expander(f"📅 {d_key}", expanded=True):
                        all_checked = all(s in existing_wishes for s in slots)
                        if st.checkbox(f"🙆‍♂️ {d_key} は何時でもOK", value=all_checked, key=f"all_{d_key}"):
                            final_selected.extend(slots)
                        else:
                            for slot in slots:
                                label = slot.replace(d_key, "").strip()
                                is_on = slot in existing_wishes
                                if st.checkbox(label, value=is_on, key=f"chk_{slot}"):
                                    final_selected.append(slot)
                
                st.markdown("---")
                if st.form_submit_button("希望を送信する", type="primary"):
                    final_selected = sorted(list(set(final_selected)), key=lambda s: current_slots.index(s) if s in current_slots else 999)
                    wishes_str = ",".join(final_selected)
                    save_requests_row(student_name, wishes_str)
                    st.success("✅ 保存しました！")
                    st.rerun()

# ==========================================
# タブ2: 先生用
# ==========================================
with tab2:
    st.header("管理者メニュー")
    
    with st.expander("📊 半期ごとのレッスン回数", expanded=False):
        df_h = load_history()
        if not df_h.empty:
            count_table = pd.crosstab(df_h["受講者"], df_h["学期"], margins=True, margins_name="合計")
            st.dataframe(count_table, use_container_width=True)
        else: st.info("履歴なし")

    st.markdown("---")
    st.subheader("📝 登録済みリスト")
    current_slots = sort_slots(load_slots())
    
    if current_slots:
        summary = group_continuous_slots(current_slots)
        for s in summary:
            st.info(f"**{s}**")
            
        with st.expander("詳細リストの編集・削除はこちら"):
            for slot in current_slots:
                col_txt, col_del = st.columns([4, 1])
                col_txt.text(f"･ {slot}")
                if col_del.button("削除", key=f"del_{slot}"):
                    new_list = [s for s in current_slots if s != slot]
                    save_slots(new_list)
                    st.rerun()
            if st.button("全削除", type="primary"):
                save_slots([]); st.rerun()
    else: st.info("登録なし")

    st.markdown("---")
    st.subheader("🪄 日程の一括作成 (50分連続枠)")
    c1, c2, c3 = st.columns(3)
    gen_date = c1.text_input("日付 (例: 9/11)", value="9/11")
    gen_start = c2.text_input("開始 (例: 10:00)", value="10:00")
    gen_end = c3.text_input("終了 (例: 13:00)", value="13:00")
    
    if st.button("プランを計算"):
        try:
            clean_date = normalize_date_text(gen_date).split(" ")[0]
            clean_start = unicodedata.normalize('NFKC', gen_start).replace("：", ":")
            clean_end = unicodedata.normalize('NFKC', gen_end).replace("：", ":")
            dummy = datetime(2000, 1, 1)
            t_s = datetime.strptime(clean_start, "%H:%M")
            t_e = datetime.strptime(clean_end, "%H:%M")
            plan_a = []
            curr = datetime.combine(dummy, t_s.time())
            limit = datetime.combine(dummy, t_e.time())
            while curr + timedelta(minutes=50) <= limit:
                nxt = curr + timedelta(minutes=50)
                plan_a.append(f"{clean_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                curr = nxt
            plan_b = []
            curr = datetime.combine(dummy, t_s.time())
            while curr < limit:
                nxt = curr + timedelta(minutes=50)
                plan_b.append(f"{clean_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                curr = nxt
            st.session_state["p_a"], st.session_state["p_b"] = plan_a, plan_b
            st.session_state["gen_info"] = f"{clean_date} {clean_start}〜{clean_end}"
        except: st.error("時間を正しく入力してください")

    if "p_a" in st.session_state:
        st.info(f"📅 **{st.session_state['gen_info']}** の提案")
        ca, cb = st.columns(2)
        with ca:
            st.markdown(f"### 🅰️ 時間内 ({len(st.session_state['p_a'])}枠)")
            for s in st.session_state['p_a']: st.text(f"･ {s}")
            if st.button("🅰️ 追加", key="btn_a"):
                current = load_slots()
                save_slots(current + st.session_state['p_a'])
                st.success("追加しました")
                del st.session_state['p_a'], st.session_state['p_b']
                st.rerun()
        with cb:
            st.markdown(f"### 🅱️ 使い切り ({len(st.session_state['p_b'])}枠)")
            for s in st.session_state['p_b']:
                if s not in st.session_state['p_a']: st.markdown(f"**･ {s} (延長)**")
                else: st.text(f"･ {s}")
            if st.button("🅱️ 追加", key="btn_b"):
                current = load_slots()
                save_slots(current + st.session_state['p_b'])
                st.success("追加しました")
                del st.session_state['p_a'], st.session_state['p_b']
                st.rerun()

    st.markdown("---")
    with st.expander("【方法B】リストを直接編集"):
        st.info("💡 「9/11 10:00」で自動補正されます。")
        current_slots_text = "\n".join(load_slots())
        edited_text = st.text_area("編集エリア", value=current_slots_text, height=200)
        if st.button("上書き保存", type="primary"):
            lines = [l.strip() for l in edited_text.split('\n') if l.strip()]
            save_slots(lines)
            st.success("保存しました！")
            st.rerun()

    st.markdown("---")
    with st.expander("👥 名簿編集"):
        cur_std = load_students()
        txt = st.text_area("リスト", "\n".join(cur_std))
        if st.button("名簿保存"):
            save_students([x.strip() for x in txt.split('\n') if x.strip()])
            st.success("保存しました"); st.rerun()

    if st.button("🤖 シフト作成 (連続2枠優先)"):
        current_slots = load_slots()
        df_req = load_requests()
        df_hist = load_history()
        
        if df_req.empty or not current_slots: st.error("データ不足")
        else:
            req_map = {}
            for _, r in df_req.iterrows():
                if pd.notna(r["希望枠"]) and r["希望枠"]: req_map[r["氏名"]] = r["希望枠"].split(",")
            slot_applicants = {s: [] for s in current_slots}
            for name, wishes in req_map.items():
                for w in wishes:
                    if w in current_slots: slot_applicants[w].append(name)
            
            final_schedule = {}
            current_batch_counts = defaultdict(int)
            daily_counts = defaultdict(lambda: defaultdict(int))
            daily_last_end = defaultdict(lambda: defaultdict(str))
            
            sorted_slots_process = sort_slots(current_slots)

            for slot in sorted_slots_process:
                cands = slot_applicants[slot]
                if not cands: continue

                semester = get_semester(slot)
                match_dt = re.match(r'(.*?)\s*(\d{1,2}:\d{2})-(\d{1,2}:\d{2})', slot)
                if match_dt: date_part, s_time, e_time = match_dt.groups()
                else: date_part, s_time, e_time = slot.split(" ")[0], "00:00", "00:00"

                scored_cands = []
                for student in cands:
                    if daily_counts[student][date_part] >= 2: continue
                    past_count = len(df_hist[ (df_hist["受講者"]==student) & (df_hist["学期"]==semester) ])
                    total_count = past_count + current_batch_counts[student]
                    penalty = 0
                    if daily_counts[student][date_part] == 1:
                        prev_end = daily_last_end[student][date_part]
                        if prev_end == s_time: penalty = -50 
                        else: penalty = 999 
                    score = total_count + penalty
                    scored_cands.append( (score, random.random(), student) )
                
                if scored_cands:
                    scored_cands.sort()
                    winner = scored_cands[0][2]
                    final_schedule[slot] = winner
                    current_batch_counts[winner] += 1
                    daily_counts[winner][date_part] += 1
                    daily_last_end[winner][date_part] = e_time
            
            res = []
            for s in sort_slots(current_slots):
                res.append({"日時": s, "受講者": final_schedule.get(s, "❌"), "学期": get_semester(s)})
            st.session_state["preview"] = pd.DataFrame(res)
            st.table(st.session_state["preview"])
            
            # ★新機能: LINE貼り付け用テキスト生成
            if not st.session_state["preview"].empty:
                st.write("#### 📋 LINE貼り付け用テキスト")
                copy_text = "【レッスン日程】\n"
                for _, row in st.session_state["preview"].iterrows():
                    if row["受講者"] and "❌" not in row["受講者"]:
                        copy_text += f"{row['日時']} : {row['受講者']}\n"
                st.code(copy_text, language="text")

    if "preview" in st.session_state:
        if st.button("確定して履歴に保存"):
            to_save = st.session_state["preview"][ st.session_state["preview"]["受講者"].str.contains("❌") == False ]
            save_history_new(to_save)
            st.success("保存完了！")
            del st.session_state["preview"]

    st.markdown("---")
    st.write("#### 🗑️ データの初期化")
    c_res1, c_res2 = st.columns(2)
    
    # ★新機能: 希望リセットボタン
    with c_res1:
        with st.expander("⚠️ 学生の「希望」を全てリセット"):
            st.warning("来月の日程調整を始める前に押してください。全ての学生の希望データが消えます。")
            if st.button("希望データを削除", type="primary"):
                supabase.table("requests").delete().neq("id", 0).execute()
                st.success("リセットしました")
                st.rerun()

    with c_res2:
        with st.expander("⚠️ レッスン履歴を全てリセット"):
            st.warning("半期が変わる時だけ使ってください。")
            if st.button("履歴を削除", type="primary"):
                supabase.table("history").delete().neq("id", 0).execute()
                st.success("リセットしました")
                st.rerun()

# ==========================================
# タブ3: 集計
# ==========================================
with tab3:
    st.header("全期間データ")
    st.dataframe(load_history())
