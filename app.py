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
st.title("🎹 レッスン日程 自動調整システム v15 (安全版)")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 関数群 ---

def normalize_date_text(text):
    text = unicodedata.normalize('NFKC', text)
    date_match = re.search(r'(\d{1,2})[\/\-月\.](\d{1,2})', text)
    if not date_match: return text
    month, day = int(date_match.group(1)), int(date_match.group(2))
    now = datetime.now()
    year = now.year
    try:
        dt = datetime(year, month, day)
    except ValueError: return text
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    wk = weekdays[dt.weekday()]
    base_date = f"{month}月{day}日({wk})"
    time_match = re.search(r'(\d{1,2}:\d{2}.*)', text)
    if time_match: return f"{base_date} {time_match.group(1)}"
    return base_date

def get_semester(date_str):
    match = re.search(r'(\d{1,2})月', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期"
        else: return "後期"
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

# --- DB操作 (エラーを握りつぶさない安全設計) ---
def load_data(sheet_name, cols):
    # try-exceptを外して、シートがない場合は明確にエラーを出す
    # ttl=0 でキャッシュを無効化
    df = conn.read(worksheet=sheet_name, usecols=list(range(cols)), ttl=0)
    return df.dropna(how="all")

def save_data(sheet_name, df):
    conn.update(worksheet=sheet_name, data=df)

# 各シートのラッパー
def load_slots():
    try:
        df = load_data("Slots", 1)
        if df.empty: return []
        # カラム名チェック
        if df.columns[0] != "候補日時":
            # もしカラム名がおかしければ、データが壊れている可能性あり
            return []
        return df["候補日時"].dropna().tolist()
    except Exception as e:
        # Slotsシート読み込みエラーは致命的なので表示するかも
        return []

def save_slots(slot_list):
    unique_list = sorted(list(set(slot_list)), key=lambda s: sort_slots([s])[0])
    save_data("Slots", pd.DataFrame({"候補日時": unique_list}))

def load_requests():
    try:
        df = load_data("Requests", 2)
        if df.shape[1] < 2: return pd.DataFrame(columns=["氏名", "希望枠"])
        return df
    except Exception:
        # シートがない場合などは空を返す
        return pd.DataFrame(columns=["氏名", "希望枠"])

def save_requests(new_df):
    save_data("Requests", new_df)

def load_history():
    try:
        df = load_data("History", 3)
        if df.shape[1] < 3: return pd.DataFrame(columns=["日時", "受講者", "学期"])
        return df
    except: return pd.DataFrame(columns=["日時", "受講者", "学期"])

def save_history(new_df):
    old_df = load_history()
    if old_df.empty: updated = new_df
    else: updated = pd.concat([old_df, new_df], ignore_index=True)
    save_data("History", updated)

def load_students():
    try:
        df = load_data("Students", 1)
        if df.empty: return []
        return df["氏名"].dropna().tolist()
    except: return []

def save_students(name_list):
    name_list = sorted(list(set(name_list)))
    save_data("Students", pd.DataFrame({"氏名": name_list}))

# --- 画面構成 ---
tab1, tab2, tab3 = st.tabs(["🙋 学生用", "📅 先生用 (登録・管理)", "📊 データ集計"])

# ==========================================
# タブ1: 学生用
# ==========================================
with tab1:
    st.header("レッスン希望の提出")
    
    # データのロード確認
    raw_slots = load_slots()
    student_list = load_students()
    
    if not raw_slots:
        st.warning("現在、募集中のレッスン枠はありません。（またはSlotsシートが読み込めません）")
        # デバッグ用：なぜ空なのか確認
        try:
            test_df = load_data("Slots", 1)
            if test_df.empty:
                st.caption("※ Slotsシートは存在しますが、データが空です。")
            elif test_df.columns[0] != "候補日時":
                st.error(f"⚠️ エラー: Slotsシートの1行目が「{test_df.columns[0]}」になっています。「候補日時」である必要があります。シートが上書きされた可能性があります。")
        except:
            st.error("⚠️ エラー: スプレッドシートに「Slots」という名前のシートが見つかりません。")

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
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    existing_wishes = row["希望枠"].split(",")
            
            st.info(f"ログイン中: **{student_name}** さん")
            
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
                            cols = st.columns(2)
                            for i, slot in enumerate(slots):
                                label = slot.replace(d_key, "").strip()
                                is_on = slot in existing_wishes
                                if cols[i % 2].checkbox(label, value=is_on, key=f"chk_{slot}"):
                                    final_selected.append(slot)
                
                st.markdown("---")
                if st.form_submit_button("希望を送信する", type="primary"):
                    final_selected = sorted(list(set(final_selected)), key=lambda s: current_slots.index(s) if s in current_slots else 999)
                    wishes_str = ",".join(final_selected)
                    new_row = {"氏名": student_name, "希望枠": wishes_str}
                    
                    # リクエストの更新処理
                    df_req = df_req[df_req["氏名"] != student_name]
                    new_df = pd.concat([df_req, pd.DataFrame([new_row])], ignore_index=True)
                    
                    try:
                        save_requests(new_df)
                        st.success("✅ 保存しました！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"保存エラー: {e}")
                        st.error("「Requests」シートが存在するか確認してください。")

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
    st.subheader("🪄 日程の一括作成 (50分連続枠)")
    
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
            st.session_state["gen_info"] = f"{norm_date} {gen_start}〜{gen_end}"
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
    st.subheader("📝 登録済みリスト")
    current_slots = load_slots()
    
    if current_slots:
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
    with st.expander("👥 名簿編集"):
        cur_std = load_students()
        txt = st.text_area("リスト", "\n".join(cur_std))
        if st.button("名簿保存"):
            save_students([x.strip() for x in txt.split('\n') if x.strip()])
            st.success("保存しました"); st.rerun()

    if st.button("🤖 シフト作成"):
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
            for slot in sort_slots(current_slots):
                cands = slot_applicants[slot]
                if cands: final_schedule[slot] = random.choice(cands)
            res = []
            for s in sort_slots(current_slots):
                res.append({"日時": s, "受講者": final_schedule.get(s, "❌"), "学期": get_semester(s)})
            st.session_state["preview"] = pd.DataFrame(res)
            st.table(st.session_state["preview"])

    if "preview" in st.session_state:
        if st.button("確定保存"):
            to_save = st.session_state["preview"][ st.session_state["preview"]["受講者"].str.contains("❌") == False ]
            save_history(to_save)
            st.success("保存完了"); del st.session_state["preview"]

# ==========================================
# タブ3: 集計
# ==========================================
with tab3:
    st.header("全期間データ")
    st.dataframe(load_history())
