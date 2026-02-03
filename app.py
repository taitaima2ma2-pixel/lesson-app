import streamlit as st
import pandas as pd
import random
import re
from datetime import datetime, timedelta
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection

# --- 設定 ---
st.set_page_config(page_title="レッスン調整システム", page_icon="🎹", layout="wide")
st.title("🎹 レッスン日程 自動調整システム v9")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 関数群 ---
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
    save_data("Slots", pd.DataFrame({"候補日時": slot_list}))

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

def get_semester(date_str):
    match = re.search(r'(\d+)/', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期 (4-8月)"
        else: return "後期 (9-2月)"
    return "不明"

def sort_slots(slot_list):
    def parse_key(s):
        try:
            match = re.search(r'(\d+)/(\d+).*?(\d+):(\d+)', s)
            if match:
                mo, d, h, m = map(int, match.groups())
                year_offset = 1 if mo <= 3 else 0
                return (year_offset, mo, d, h, m)
            return (99, 99, 99, 99, 99)
        except: return (99, 99, 99, 99, 99)
    return sorted(slot_list, key=parse_key)

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用: 希望提出", "📅 先生用: 管理・登録", "📊 データ集計"])

# ==========================================
# タブ1: 学生用 (完全リスト選択式)
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
        
        # --- 名前選択エリア ---
        student_name = ""
        
        if not student_list:
            st.error("⚠️ 名簿が登録されていません。先生用タブで学生を追加してください。")
        else:
            # プレースホルダー付きのセレクトボックス
            selected_val = st.selectbox("自分の名前を選んでください", ["(名前を選択してください)"] + student_list)
            
            if selected_val != "(名前を選択してください)":
                student_name = selected_val
            else:
                st.info("☝️ 上のリストから自分の名前を選んでください。\n\n※ 名前がない場合は、先生に連絡して登録してもらってください。")

        # --- 以下、希望入力フォーム ---
        existing_wishes = []
        if student_name:
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    existing_wishes = row["希望枠"].split(",")
                    st.info(f"💡 {student_name}さんは現在、**{len(existing_wishes)}件** の希望を提出済みです。")
                else:
                    st.info(f"💡 {student_name}さんの希望はまだ登録されていません。")
            
            st.markdown("---")
            st.write("▼ 参加できる日時を選んでください")
            
            slots_by_date = defaultdict(list)
            for slot in current_slots:
                date_key = slot.split(" ")[0]
                slots_by_date[date_key].append(slot)
                
            with st.form("student_form"):
                selected = []
                for date_key, slots_in_date in slots_by_date.items():
                    with st.expander(f"📅 {date_key}", expanded=True): 
                        cols = st.columns(2)
                        for i, slot in enumerate(slots_in_date):
                            chk_key = f"chk_{date_key}_{i}"
                            is_checked = slot in existing_wishes
                            label_text = slot.split(" ", 1)[1] if " " in slot else slot
                            if cols[i % 2].checkbox(f"{label_text}", value=is_checked, key=chk_key):
                                selected.append(slot)
                
                st.markdown("---")
                if st.form_submit_button("希望を送信 / 更新する", type="primary"):
                    wishes_str = ",".join(selected)
                    new_row = {"氏名": student_name, "希望枠": wishes_str}
                    
                    df_req = df_req[df_req["氏名"] != student_name]
                    new_df = pd.concat([df_req, pd.DataFrame([new_row])], ignore_index=True)
                    save_requests(new_df)
                    
                    st.balloons()
                    st.success(f"✅ {student_name}さんの希望を保存しました！")
                    st.rerun()

# ==========================================
# タブ2: 先生用
# ==========================================
with tab2:
    st.header("管理者メニュー")
    
    # --- 学生名簿管理 ---
    with st.expander("👥 学生名簿の管理 (名前の追加・削除)", expanded=True):
        current_students = load_students()
        st.caption("改行区切りで名前を入力し、保存してください。")
        default_std_text = "\n".join(current_students)
        new_std_text = st.text_area("学生リスト", value=default_std_text, height=150)
        
        if st.button("名簿を更新して保存"):
            new_std_list = [line.strip() for line in new_std_text.split('\n') if line.strip()]
            save_students(new_std_list)
            st.success("名簿を更新しました！タブ1で確認できます。")
            st.rerun()

    st.markdown("---")
    st.subheader("候補日の登録")

    # --- 既存スロット管理 ---
    current_slots = load_slots()
    if current_slots:
        st.write(f"✅ 現在 **{len(current_slots)}枠** が登録されています。")
        with st.expander("現在のリストを確認・手動編集"):
            default_text = "\n".join(sort_slots(current_slots))
            edited_text = st.text_area("直接編集エリア", value=default_text, height=200)
            if st.button("手動編集を保存"):
                new_list = [line.strip() for line in edited_text.split('\n') if line.strip()]
                save_slots(new_list)
                st.success("更新しました")
                st.rerun()
            if st.button("全削除する", type="primary"):
                save_slots([])
                st.rerun()
    else:
        st.info("登録枠なし")

    # --- 新規追加ウィザード ---
    st.markdown("#### 🪄 日程の一括作成")
    c1, c2, c3 = st.columns(3)
    gen_date = c1.text_input("日付 (例: 10/4(土))", value="10/4(土)")
    gen_start = c2.text_input("開始時間 (例: 10:00)", value="10:00")
    gen_end = c3.text_input("終了時間 (例: 12:30)", value="12:30")
    
    if st.button("プランを計算・プレビュー"):
        try:
            dummy = datetime(2000, 1, 1)
            t_start = datetime.strptime(gen_start, "%H:%M")
            t_end = datetime.strptime(gen_end, "%H:%M")
            
            # Plan A
            plan_a = []
            curr = datetime.combine(dummy, t_start.time())
            limit = datetime.combine(dummy, t_end.time())
            while curr + timedelta(minutes=50) <= limit:
                nxt = curr + timedelta(minutes=50)
                plan_a.append(f"{gen_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                curr = nxt
            
            # Plan B
            plan_b = []
            curr = datetime.combine(dummy, t_start.time())
            while curr < limit:
                nxt = curr + timedelta(minutes=50)
                plan_b.append(f"{gen_date} {curr.strftime('%H:%M')}-{nxt.strftime('%H:%M')}")
                curr = nxt
            
            st.session_state["plan_a"] = plan_a
            st.session_state["plan_b"] = plan_b
            st.session_state["gen_info"] = f"{gen_date} {gen_start}〜{gen_end}"
        except ValueError: st.error("時間形式エラー")

    if "plan_a" in st.session_state:
        st.info(f"📅 **{st.session_state['gen_info']}** の提案")
        ca, cb = st.columns(2)
        with ca:
            st.markdown("### 🅰️ 時間内")
            for s in st.session_state["plan_a"]: st.text(f"･ {s}")
            if st.button("🅰️ 追加", key="Ba"):
                save_slots(sort_slots(load_slots() + st.session_state["plan_a"]))
                del st.session_state["plan_a"]; del st.session_state["plan_b"]
                st.rerun()
        with cb:
            st.markdown("### 🅱️ 使い切り")
            for s in st.session_state["plan_b"]:
                if s not in st.session_state["plan_a"]: st.markdown(f"**･ {s} (延)**")
                else: st.text(f"･ {s}")
            if st.button("🅱️ 追加", key="Bb"):
                save_slots(sort_slots(load_slots() + st.session_state["plan_b"]))
                del st.session_state["plan_a"]; del st.session_state["plan_b"]
                st.rerun()

    st.markdown("---")
    st.subheader("シフト自動作成")
    if st.button("シフトを組む"):
        current_slots = sort_slots(load_slots())
        df_req = load_requests()
        if df_req.empty or not current_slots: st.error("データ不足")
        else:
            req_dict = {row["氏名"]: row["希望枠"].split(",") for _, row in df_req.iterrows() if pd.notna(row["希望枠"]) and row["希望枠"]}
            final_schedule = {}
            student_counts = defaultdict(int)
            daily_counts = defaultdict(lambda: defaultdict(int))
            slot_applicants = {s: [] for s in current_slots}
            for name, wishes in req_dict.items():
                for w in wishes:
                    if w in current_slots: slot_applicants[w].append(name)
            
            sorted_slots = sorted([s for s in current_slots if slot_applicants[s]], key=lambda s: len(slot_applicants[s]))
            
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
            
            res_list = [{"日時": s, "受講者": final_schedule.get(s, ""), "学期": get_semester(s)} for s in current_slots if s in final_schedule]
            if res_list:
                st.session_state["preview"] = pd.DataFrame(res_list)
                st.table(st.session_state["preview"])
            else: st.warning("成立なし")

    if "preview" in st.session_state:
        if st.button("確定して履歴保存"):
            save_history(st.session_state["preview"])
            st.success("保存完了")
            del st.session_state["preview"]

# ==========================================
# タブ3: 集計
# ==========================================
with tab3:
    st.header("集計")
    df_hist = load_history()
    if df_hist.empty: st.info("履歴なし")
    else:
        try:
            pivot = pd.crosstab(df_hist["受講者"], df_hist["学期"], margins=True, margins_name="合計")
            st.dataframe(pivot)
        except: st.error("集計エラー")
