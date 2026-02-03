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
st.title("🎹 レッスン日程 自動調整システム v13")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 関数群 ---

def normalize_date_text(text):
    # 日付(M/D)を "M月D日(曜日)" に変換する
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
    return f"{month}月{day}日({wk})"

def get_semester(date_str):
    # 学期判定 (4-8月:前期, 9-3月:後期)
    match = re.search(r'(\d{1,2})月', date_str)
    if match:
        month = int(match.group(1))
        if 4 <= month <= 8: return "前期"
        else: return "後期"
    return "不明"

def sort_slots(slot_list):
    # 日付順・時間順に並べ替え
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
    # 重複排除とソートをして保存
    unique_list = sorted(list(set(slot_list)), key=lambda s: sort_slots([s])[0])
    save_data("Slots", pd.DataFrame({"候補日時": unique_list}))

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
            existing_wishes = []
            if not df_req.empty and student_name in df_req["氏名"].values:
                row = df_req[df_req["氏名"] == student_name].iloc[0]
                if pd.notna(row["希望枠"]) and row["希望枠"]:
                    existing_wishes = row["希望枠"].split(",")
            
            st.info(f"ログイン中: **{student_name}** さん")
            
            # 日付グループ化
            slots_by_date = defaultdict(list)
            for slot in current_slots:
                # "9月11日(木)" の部分をキーにする
                d_key = slot.split(" ")[0]
                slots_by_date[d_key].append(slot)

            with st.form("student_form"):
                final_selected = []
                for d_key, slots in slots_by_date.items():
                    with st.expander(f"📅 {d_key}", expanded=True):
                        # 全選択オプション
                        all_checked = all(s in existing_wishes for s in slots)
                        if st.checkbox(f"🙆‍♂️ {d_key} は何時でもOK", value=all_checked, key=f"all_{d_key}"):
                            # 全選択ならこの日の全スロットを追加
                            final_selected.extend(slots)
                        else:
                            # 個別選択
                            cols = st.columns(2)
                            for i, slot in enumerate(slots):
                                # 時間部分のみ表示 "10:00-10:50"
                                label = slot.replace(d_key, "").strip()
                                is_on = slot in existing_wishes
                                if cols[i % 2].checkbox(label, value=is_on, key=f"chk_{slot}"):
                                    final_selected.append(slot)
                
                st.markdown("---")
                if st.form_submit_button("希望を送信する", type="primary"):
                    # 重複除去して保存
                    final_selected = sorted(list(set(final_selected)), key=lambda s: current_slots.index(s) if s in current_slots else 999)
                    wishes_str = ",".join(final_selected)
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
    
    # 1. レッスン回数カウンター (NEW!)
    with st.expander("📊 半期ごとのレッスン回数を確認", expanded=False):
        df_h = load_history()
        if not df_h.empty:
            # ピボットテーブルで見やすく
            count_table = pd.crosstab(df_h["受講者"], df_h["学期"], margins=True, margins_name="合計")
            st.dataframe(count_table, use_container_width=True)
        else:
            st.info("まだ履歴がありません。")

    st.markdown("---")
    
    # 2. 1件ずつ確実に追加
    st.subheader("➕ レッスン枠の追加")
    st.caption("日付と開始時間を入力してください。自動で **50分枠** として登録されます。")
    
    c1, c2, c3 = st.columns([2, 2, 1])
    in_date = c1.text_input("日付 (例: 9/11)", value="")
    in_time = c2.text_input("開始時間 (例: 10:00)", value="")
    
    if c3.button("追加する", type="primary"):
        if in_date and in_time:
            try:
                # 日付整形
                norm_date = normalize_date_text(in_date)
                # 時間計算
                t_start = datetime.strptime(in_time, "%H:%M")
                t_end = t_start + timedelta(minutes=50)
                
                # 文字列結合: "9月11日(木) 10:00-10:50"
                new_slot = f"{norm_date} {t_start.strftime('%H:%M')}-{t_end.strftime('%H:%M')}"
                
                # 保存
                current = load_slots()
                if new_slot in current:
                    st.warning("その枠は既にあります。")
                else:
                    save_slots(current + [new_slot])
                    st.success(f"追加しました: {new_slot}")
                    st.rerun()
            except:
                st.error("入力形式を確認してください (例: 10:00)")
        else:
            st.warning("日付と時間を入力してください")

    # 3. 現在のリスト管理
    st.markdown("---")
    st.subheader("📝 現在の登録リスト")
    current_slots = load_slots()
    
    if current_slots:
        # 削除機能付きリスト表示
        for slot in current_slots:
            col_txt, col_del = st.columns([4, 1])
            col_txt.text(f"･ {slot}")
            if col_del.button("削除", key=f"del_{slot}"):
                new_list = [s for s in current_slots if s != slot]
                save_slots(new_list)
                st.rerun()
                
        # 全削除ボタン
        if st.button("全ての枠を削除する"):
            save_slots([])
            st.rerun()
    else:
        st.info("登録枠なし")

    # 4. 学生名簿
    st.markdown("---")
    with st.expander("👥 学生名簿の編集"):
        cur_std = load_students()
        txt = st.text_area("リスト (改行区切り)", "\n".join(cur_std))
        if st.button("名簿保存"):
            save_students([x.strip() for x in txt.split('\n') if x.strip()])
            st.success("保存しました")
            st.rerun()

    # 5. シフト作成 (簡易版)
    st.markdown("---")
    if st.button("🤖 シフトを自動で割り振る"):
        current_slots = load_slots()
        df_req = load_requests()
        df_hist = load_history()
        
        if df_req.empty or not current_slots:
            st.error("データ不足")
        else:
            # 申し込み展開
            req_map = {}
            for _, r in df_req.iterrows():
                if pd.notna(r["希望枠"]) and r["希望枠"]:
                    req_map[r["氏名"]] = r["希望枠"].split(",")
            
            # 枠ごとの希望者リスト
            slot_applicants = {s: [] for s in current_slots}
            for name, wishes in req_map.items():
                for w in wishes:
                    if w in current_slots: slot_applicants[w].append(name)
            
            final_schedule = {}
            # 今期の回数辞書を作る
            counts = defaultdict(int)
            # (簡易ロジック: Historyの回数が少ない人を優先)
            
            # マッチング
            for slot in sort_slots(current_slots):
                cands = slot_applicants[slot]
                if not cands: continue
                
                # 候補者をシャッフルしてランダム選出 (ここは必要なら優先度ロジックに戻せます)
                # 今回はシンプルにランダム
                winner = random.choice(cands)
                
                # 重複チェック (同日2コマなどの厳密チェックは今回省略、シンプル割り当て)
                final_schedule[slot] = winner
            
            # 結果表示
            res = []
            for s in sort_slots(current_slots):
                winner = final_schedule.get(s, "❌ (不成立)")
                res.append({"日時": s, "受講者": winner, "学期": get_semester(s)})
            
            st.session_state["preview"] = pd.DataFrame(res)
            st.table(st.session_state["preview"])

    if "preview" in st.session_state:
        if st.button("確定して履歴に保存"):
            to_save = st.session_state["preview"][ st.session_state["preview"]["受講者"].str.contains("❌") == False ]
            save_history(to_save)
            st.success("保存完了！")
            del st.session_state["preview"]

# ==========================================
# タブ3: データ集計 (予備)
# ==========================================
with tab3:
    st.header("全期間データ")
    df_h = load_history()
    st.dataframe(df_h)
