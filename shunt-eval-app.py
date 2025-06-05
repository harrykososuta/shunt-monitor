import streamlit as st
st.set_page_config(page_title="シャント機能評価", layout="wide")

from streamlit_calendar import calendar
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import uuid
import os
import sqlite3
import seaborn as sns
import pytz
from scipy.stats import mannwhitneyu
from fpdf import FPDF
from io import BytesIO

from datetime import datetime, time

from supabase import create_client, Client
# Supabase 接続設定
url = "https://wlozruvtxaoagnumolkr.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Indsb3pydXZ0eGFvYWdudW1vbGtyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQ4NTg0MDAsImV4cCI6MjA2MDQzNDQwMH0.o9o1bhEhXyAYhrQIhuevWuDzJxASG-DSb7IqXIz_Huw"
supabase: Client = create_client(url, key)

from dotenv import load_dotenv

# --- スタイル設定 ---
matplotlib.rcParams['font.family'] = 'MS Gothic'

# --- シミュレーション用の定数（復元済み） ---
baseline_FV = 380
baseline_RI = 0.68
baseline_diameter = 5.0

coefficients = {
    "PSV": [37.664, 0.0619, 52.569, -1.2],
    "EDV": [69.506, 0.0305, -74.499, -0.8],
    "TAV": [45.0, 0.031, -33.0, -0.5],
    "TAMV": [64.5, 0.044, -29.5, -1.0]
}

# --- シミュレーション用の関数 ---
def calculate_parameter(FV, RI, diameter, coeffs):
    return coeffs[0] + coeffs[1]*FV + coeffs[2]*RI + coeffs[3]*diameter

def calculate_tavr(TAV, TAMV):
    return TAV / TAMV if TAMV != 0 else 0

# --- .env 読み込み ---
load_dotenv()

# --- Supabase 初期化 ---
try:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL または SUPABASE_KEY が設定されていません。")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Supabase 認証エラー: {e}")
    st.stop()

# --- ユーティリティ関数 ---
def generate_access_code(index):
    return f"shunt{str(index).zfill(4)}"

def authenticate_user(password, access_code):
    res = supabase.table("users").select("*").eq("password", password).eq("access_code", access_code).execute()
    return res.data if res.data else None

def register_user(password):
    res = supabase.table("users").select("*").eq("password", password).execute()
    if res.data:
        return None
    count_res = supabase.table("users").select("*").execute()
    access_code = generate_access_code(len(count_res.data) + 1)
    supabase.table("users").insert({"password": password, "access_code": access_code}).execute()
    return access_code

# 日本語→英語変換辞書
jp_to_en = {
    "検査日": "Date",
    "氏名": "Patient",
    "VA Type": "VA Type",
    "評価パラメータ": "Parameters",
    "コメント": "Comment",
    "評価スコア": "Evaluation Score",
    "所見コメント": "Clinical Comment",
    "次回検査日": "Next Exam Date",
    "評価結果": "Threshold Evaluation",
    "透析後に評価": "Evaluate post-dialysis",
    "次回透析日に評価": "Evaluate next dialysis",
    "経過観察": "Follow-up",
    "VAIVT提案": "VAIVT recommended"
}

# --- セッション初期化 ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'password' not in st.session_state:
    st.session_state.password = ""
if 'new_user' not in st.session_state:
    st.session_state.new_user = None
if 'page' not in st.session_state:
    st.session_state.page = "ToDoリスト"  # ログイン後の初期ページを指定

# --- ログインページ ---
if not st.session_state.get("authenticated", False):
    st.sidebar.empty()
    st.title("🔐 シャント機能評価ツール - ログイン")

    # 新規 or 既存ユーザー選択
    user_type = st.radio("ご利用は初めてですか？", ["はい（新規）", "いいえ（既存ユーザー）"])
    st.session_state.new_user = user_type == "はい（新規）"

    # パスワード入力（4桁）
    password_input = st.text_input("4桁のパスワードを入力してください", type="password")

    # --- 新規登録 ---
    if st.session_state.new_user:
        if len(password_input) == 4 and password_input.isdigit():
            if st.button("登録する"):
                access_code = register_user(password_input)
                if access_code:
                    st.session_state.generated_access_code = access_code
                    st.session_state.password = password_input
                    st.session_state.registered = True
                else:
                    st.warning("⚠ このパスワードはすでに使用されています。他のものを使用してください。")
        else:
            st.info("※ 4桁の数字で入力してください")

        if st.session_state.get("registered", False):
            st.success(f"✅ 登録完了！あなたのアクセスコードは `{st.session_state.generated_access_code}` です。")
            st.code(st.session_state.generated_access_code)
            st.error("⚠ このアクセスコードは再度表示できません。必ずメモやスクリーンショット等で保存してください。")
            if st.button("アプリを開始"):
                st.session_state.authenticated = True
                st.session_state.page = "ToDoリスト"
                st.rerun()

    # --- 既存ログイン ---
    else:
        access_code = st.text_input("アクセスコードを入力してください")
        if len(password_input) == 4 and password_input.isdigit() and access_code:
            if st.button("アプリを開始"):
                user = authenticate_user(password_input, access_code)
                if user:
                    st.success("✅ ログイン成功！")
                    st.session_state.authenticated = True
                    st.session_state.password = password_input
                    st.session_state.generated_access_code = access_code
                    st.session_state.page = "ToDoリスト"
                    st.rerun()
                else:
                    st.error("❌ パスワードまたはアクセスコードが正しくありません")

    st.stop()

# --- ログイン済みユーザーの処理 ---
if st.session_state.authenticated:

    # --- サイドバー（ページ選択 & ログアウト） ---
    with st.sidebar:
        st.title("ページ選択")
        st.session_state.page = st.radio(
            "",
            ["ToDoリスト", "シミュレーションツール", "評価フォーム", "記録一覧とグラフ", "患者管理", "患者データ一覧"],
            key="main_page_selector"
        )

        if st.button("ログアウト"):
            st.session_state.authenticated = False
            st.session_state.new_user = None
            st.session_state.page = ""
            st.rerun()

    # --- ページ分岐処理 ---
    page = st.session_state.page

    if page == "ToDoリスト":
        st.title("📝 ToDoリスト・タスク管理")
        st.info("ToDoリスト機能を実装する場所")
        # ToDoリストの処理（中身をここに移動）

    elif page == "シミュレーションツール":
        st.title("🔢 シミュレーションツール")
        st.info("計算や予測ツールを追加")
        # シミュレーションの処理（ここに記述）

    elif page == "評価フォーム":
        st.title("📝 シャント機能評価フォーム")

    elif page == "記録一覧とグラフ":
        st.title("📊 記録一覧とグラフ")
        st.info("記録一覧、グラフなどを表示")
        # 記録＆グラフの表示処理ここに書く

    elif page == "患者管理":
        st.title("🗂️ 患者管理")
        st.info("患者別のアクセスや権限を管理")
        # 管理ページの中身ここに

    elif page == "患者データ一覧":
        st.title("🧾 患者データ一覧")
        st.info("全データをリストで表示")
        # Boxplotやデータ一覧処理をここに

def show_todo_page():
    st.title("📝 ToDoリスト")
    ...

def show_evaluation_page():
    st.title("機能評価で管理する")
    ...

if page == "ToDoリスト":
    show_todo_page()
elif page == "評価フォーム":
    show_evaluation_page()


    # ユーザーごとの DB 接続
    user_dir = f"data/user_{st.session_state.password}"
    DB_FILE = os.path.join(user_dir, "shunt_data.db")
    os.makedirs(user_dir, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS shunt_records (
        id INTEGER PRIMARY KEY,
        anon_id TEXT,
        name TEXT,
        date TEXT,
        FV REAL,
        RI REAL,
        PI REAL,
        TAV REAL,
        TAMV REAL,
        PSV REAL,
        EDV REAL,
        score INTEGER,
        comment TEXT,
        tag TEXT,
        note TEXT
    )''')
    conn.commit()
        # --- 本日の検査予定 followups テーブルから matches を定義 ---
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                comment TEXT,
                followup_at DATE,
                created_at TIMESTAMP
            )
        """)
        followups_df = pd.read_sql_query("SELECT name, comment, followup_at FROM followups", conn)
        followups_df["followup_at"] = pd.to_datetime(followups_df["followup_at"])
        today = pd.Timestamp.now(tz="Asia/Tokyo").normalize()
        matches = followups_df[followups_df["followup_at"].dt.date == today.date()]
    except Exception as e:
        matches = pd.DataFrame()

# --- ToDoリストのページ ---
if st.session_state.authenticated:
    if st.session_state.page == "ToDoリスト":
        from datetime import datetime, time, date

        # Safe title rendering without fallback ellipsis
        st.markdown("""
        <style>
        .title-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 0.5rem;
        }
        .title-row h1 {
            margin: 0;
            font-size: 2.2rem;
        }
        </style>
        <div class="title-row">
            <span style="font-size: 2.5rem;">📋</span>
            <h1>ToDoリスト</h1>
        </div>
        """, unsafe_allow_html=True)

        # --- 中段：2カラムでリストとフォーム ---
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("🔔 本日の検査予定")
            try:
                followups_response = supabase.table("followups") \
                    .select("name, comment, followup_at") \
                    .eq("access_code", st.session_state.generated_access_code) \
                    .execute()
                followups_df = pd.DataFrame(followups_response.data)
                followups_df["followup_at"] = pd.to_datetime(followups_df["followup_at"])
                today = pd.Timestamp.now(tz="Asia/Tokyo").normalize()
                matches = followups_df[followups_df["followup_at"].dt.date == today.date()]
            except Exception:
                matches = pd.DataFrame()

            if not matches.empty:
                if "checked_items" not in st.session_state:
                    st.session_state.checked_items = {}
                unchecked_names = []
                for i, row in matches.iterrows():
                    key = f"check_{i}"
                    if key not in st.session_state.checked_items:
                        st.session_state.checked_items[key] = False
                    check_col1, check_col2 = st.columns([1, 20])
                    with check_col1:
                        checked = st.checkbox("", key=key)
                        st.session_state.checked_items[key] = checked
                    with check_col2:
                        with st.container(border=True):
                            st.markdown(f"🧑‍⚕️ {row['name']} さん - コメント: {row['comment']}")
                    if not st.session_state.checked_items[key]:
                        unchecked_names.append(row['name'])

                if all(st.session_state.checked_items.values()):
                    st.success("本日の検査予定はありません。")
                elif unchecked_names:
                    st.warning(f"{', '.join(unchecked_names)} さんの検査が未実施です")
            else:
                st.info("本日の検査予定はありません。")

        with col2:
            st.subheader("🗓 タスク追加")
            task_date = st.date_input("タスク日を選択", value=date.today(), key="task_date_input")
            c1, c2 = st.columns(2)
            with c1:
                start_time = st.time_input("開始時刻", value=time(9, 0), key="start_time_input")
            with c2:
                end_time = st.time_input("終了時刻", value=time(9, 30), key="end_time_input")
            task_text = st.text_input("タスク内容を入力", key="task_text_input")
            if st.button("追加", key="add_task_button"):
                try:
                    start_datetime = datetime.combine(task_date, start_time)
                    end_datetime = datetime.combine(task_date, end_time)
                    supabase.table("tasks").insert({
                        "date": task_date.isoformat(),
                        "start": start_datetime.isoformat(),
                        "end": end_datetime.isoformat(),
                        "content": task_text,
                        "access_code": st.session_state.generated_access_code
                    }).execute()
                    st.success("タスクを追加しました")
                    st.rerun()
                except Exception as e:
                    st.error(f"タスクの追加に失敗しました: {e}")

        # --- カレンダー表示 ---
        st.subheader("🗓 タスクカレンダー")
        try:
            task_response = supabase.table("tasks") \
                .select("start, end, content") \
                .eq("access_code", st.session_state.generated_access_code) \
                .execute()
            task_df = pd.DataFrame(task_response.data)
            task_df.dropna(subset=["start", "end", "content"], inplace=True)
            task_df["start"] = pd.to_datetime(task_df["start"])
            task_df["end"] = pd.to_datetime(task_df["end"])

            events = [
                {
                    "title": row["content"],
                    "start": row["start"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "end": row["end"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "allDay": False,
                    "resourceId": "default"
                }
                for _, row in task_df.iterrows()
            ]

            from streamlit_calendar import calendar
            calendar(events=events, options={
                "initialView": "dayGridMonth",
                "headerToolbar": {
                    "start": "today prev,next",
                    "center": "title",
                    "end": "dayGridMonth,timeGridWeek,timeGridDay,listWeek"
                },
                "locale": "ja",
                "selectable": True,
                "editable": False,
                "navLinks": True,
                "height": 600,
                "resources": [{"id": "default", "title": "スケジュール"}]
            }, key="calendar")
        except Exception as e:
            st.warning(f"カレンダー表示に失敗しました: {e}")

        # --- タスク編集 ---
        st.subheader("🗕 登録済みタスク一覧（本日のみ）")
        try:
            task_response = supabase.table("tasks") \
                .select("start, end, content") \
                .eq("access_code", st.session_state.generated_access_code) \
                .order("start", desc=False) \
                .execute()
            task_df = pd.DataFrame(task_response.data)
            task_df.dropna(subset=["start", "end", "content"], inplace=True)
            task_df["start"] = pd.to_datetime(task_df["start"])
            task_df["end"] = pd.to_datetime(task_df["end"])
            today = pd.Timestamp.now(tz="Asia/Tokyo").normalize()
            today_df = task_df[task_df["start"].dt.date == today.date()]

            if today_df.empty:
                st.info("本日登録されたタスクはありません。")
            else:
                task_options = [f"{row['start'].strftime('%H:%M')} - {row['content']}" for _, row in today_df.iterrows()]
                selected = st.selectbox("編集するタスクを選択", options=[""] + task_options)

                if selected:
                    index = task_options.index(selected)
                    row = today_df.iloc[index]
                    new_content = st.text_input("内容修正", value=row["content"])
                    time_col1, time_col2 = st.columns(2)
                    with time_col1:
                        new_start = st.time_input("⏰ 開始", value=row["start"].time(), key=f"start_{index}")
                    with time_col2:
                        new_end = st.time_input("⏰ 終了", value=row["end"].time(), key=f"end_{index}")
                    button_col1, button_col2 = st.columns(2)
                    with button_col1:
                        if st.button("修正", key=f"edit_{index}"):
                            try:
                                new_start_datetime = datetime.combine(today, new_start)
                                new_end_datetime = datetime.combine(today, new_end)
                                supabase.table("tasks") \
                                    .update({
                                        "start": new_start_datetime.isoformat(),
                                        "end": new_end_datetime.isoformat(),
                                        "content": new_content
                                    }) \
                                    .match({
                                        "start": row["start"].isoformat(),
                                        "content": row["content"],
                                        "access_code": st.session_state.generated_access_code
                                    }) \
                                    .execute()
                                st.session_state.task_edit_success = True
                                st.rerun()
                            except:
                                st.session_state.task_edit_error = True
                                st.rerun()
                    with button_col2:
                        if st.button("削除", key=f"delete_{index}"):
                            try:
                                supabase.table("tasks") \
                                    .delete() \
                                    .match({
                                        "start": row["start"].isoformat(),
                                        "content": row["content"],
                                        "access_code": st.session_state.generated_access_code
                                    }) \
                                    .execute()
                                st.session_state.task_delete_success = True
                                st.rerun()
                            except:
                                st.session_state.task_delete_error = True
                                st.rerun()
        except Exception:
            st.warning("タスク一覧の取得に失敗しました")

        # --- メッセージ表示 ---
        if st.session_state.get("task_edit_success"):
            st.success("タスクを修正しました。")
            st.session_state.task_edit_success = False
        if st.session_state.get("task_edit_error"):
            st.error("修正に失敗しました。")
            st.session_state.task_edit_error = False
        if st.session_state.get("task_delete_success"):
            st.success("タスクを削除しました。")
            st.session_state.task_delete_success = False
        if st.session_state.get("task_delete_error"):
            st.error("削除に失敗しました。")
            st.session_state.task_delete_error = False
            
# --- シミュレーションツール ページ ---
if st.session_state.authenticated and page == "シミュレーションツール":
    st.title("シャント機能評価シミュレーションツール")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        FV = st.slider("血流量 FV (ml/min)", min_value=100, max_value=2000, value=int(baseline_FV), step=10)
        RI = st.slider("抵抗指数 RI", min_value=0.4, max_value=1.0, value=float(baseline_RI), step=0.01)
        diameter = st.slider("血管径 (mm)", min_value=3.0, max_value=7.0, value=baseline_diameter, step=0.1)

    PSV = calculate_parameter(FV, RI, diameter, coefficients["PSV"])
    EDV = calculate_parameter(FV, RI, diameter, coefficients["EDV"])
    TAV = calculate_parameter(FV, RI, diameter, coefficients["TAV"])
    TAMV = calculate_parameter(FV, RI, diameter, coefficients["TAMV"])
    PI = (PSV - EDV) / TAMV if TAMV != 0 else 0
    TAVR = calculate_tavr(TAV, TAMV)

    st.subheader("主要パラメータ")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("PSV (cm/s)", f"{PSV:.2f}")
        st.metric("EDV (cm/s)", f"{EDV:.2f}")
        st.metric("PI", f"{PI:.2f}")
    with col2:
        st.metric("TAV (cm/s)", f"{TAV:.2f}")
        st.metric("TAMV (cm/s)", f"{TAMV:.2f}")
        st.metric("TAVR", f"{TAVR:.2f}")


if st.session_state.authenticated and page == "評価フォーム":
    from datetime import datetime, date

    try:
        access_code = st.session_state.generated_access_code
        df_names = supabase.table("shunt_records") \
            .select("name") \
            .neq("name", "") \
            .eq("access_code", access_code) \
            .execute()
        name_list = list({entry['name'] for entry in df_names.data})
    except Exception as e:
        st.error(f"名前一覧の取得エラー: {e}")
        name_list = []

    with st.container(border=True):
        st.subheader("📝 評価フォーム 入力")
        name_option = st.radio("患者名の入力方法", ["新規入力", "過去から選択"])
        col_date, col_name = st.columns(2)
        with col_date:
            date_selected = st.date_input("記録日を選択", value=date.today())
        with col_name:
            if name_option == "新規入力":
                name = st.text_input("氏名（任意）※本名では記入しないでください")
            else:
                name = st.selectbox("過去の患者名から選択", name_list)

        col_tag, col_va = st.columns(2)
        with col_tag:
            tag = st.selectbox("特記事項", ["術前評価", "術後評価", "定期評価", "VAIVT前評価", "VAIVT後評価"])
        with col_va:
            va_type = st.selectbox("VAの種類", ["AVF", "AVG", "動脈表在化"], index=0)

        col_fv, col_tav = st.columns(2)
        with col_fv:
            fv = st.number_input("FV（血流量, ml/min）", min_value=0.0, value=400.0)
        with col_tav:
            tav = st.number_input("TAV（時間平均流速, cm/s）", min_value=0.0, value=60.0)

        tamv = st.number_input("TAMV（時間平均最大速度, cm/s）", min_value=0.0, value=100.0)

        col_ri, col_pi = st.columns(2)
        with col_ri:
            ri = st.number_input("RI（抵抗指数）", min_value=0.0, value=0.6)
        with col_pi:
            pi = st.number_input("PI（脈波指数）", min_value=0.0, value=1.0)

        col_psv, col_edv = st.columns(2)
        with col_psv:
            psv = st.number_input("PSV（収縮期最大速度, cm/s）", min_value=0.0, value=120.0)
        with col_edv:
            edv = st.number_input("EDV（拡張期末速度, cm/s）", min_value=0.0, value=50.0)

    st.subheader("🔍 自動評価スコア")
    score = 0
    comments = []
    if tav <= 34.5:
        score += 1
        comments.append(("warning", "TAVが34.5 cm/s以下 → 低血流が疑われる"))
    if ri >= 0.68:
        score += 1
        comments.append(("warning", "RIが0.68以上 → 高抵抗が疑われる"))
    if pi >= 1.3:
        score += 1
        comments.append(("warning", "PIが1.3以上 → 脈波指数が高い"))
    if edv <= 40.4:
        score += 1
        comments.append(("warning", "EDVが40.4 cm/s以下 → 拡張期血流速度が低い"))

    st.write(f"評価スコア: {score} / 4")
    if score == 0:
        st.success("🟢 正常：経過観察が推奨されます")
    elif score in [1, 2]:
        st.warning("🟡 要注意：追加評価が必要です")
    else:
        st.error("🔴 高リスク：専門的な評価が必要です")

    if comments:
        st.write("### 評価コメント")
        for level, comment in comments:
            if level == "warning":
                st.warning(f"- {comment}")
            else:
                st.write(f"- {comment}")

     # --- AI診断ブロック ---
    with st.container(border=True):
        with st.expander("🤖 AIによる診断コメントを表示 / 非表示"):
            if st.button("AI診断を実行"):
                ai_main_comment = ""
                ai_supplement = ""

                # 最優先診断
                if form["tav"] < 34.5 and form["pi"] >= 1.3 and form["edv"] < 40.4:
                    ai_main_comment = "TAVおよびEDVの低下に加え、PIが上昇。吻合部近傍の高度狭窄が強く疑われます。VAIVT提案を検討してください"
                elif form["tav"] < 34.5 and form["pi"] >= 1.3:
                    ai_main_comment = "TAVの低下に加え、PIが上昇。吻合部近傍の高度狭窄が疑われます"
                elif form["tav"] < 34.5 and form["edv"] < 40.4 and form["pi"] < 1.3:
                    ai_main_comment = "TAVとEDVが低下しており、中等度の吻合部狭窄が疑われます"
                elif form["tav"] < 34.5 and form["edv"] >= 40.4:
                    ai_main_comment = "TAVが低下しており、軽度の吻合部狭窄の可能性があります"
                elif form["ri"] >= 0.68 and form["edv"] < 40.4:
                    ai_main_comment = "RIが高く、EDVが低下。末梢側の狭窄が疑われます"
                elif form["ri"] >= 0.68:
                    ai_main_comment = "RIが上昇しています。末梢抵抗の増加が示唆されますが、他のパラメータ異常がないため再検が必要です"
                elif form["fv"] < 500:
                    ai_main_comment = "血流量がやや低下しています。経過観察が望まれますが、他のパラメータ異常がないため再検が必要です"
                elif score == 0:
                    ai_main_comment = "正常だと思います。経過観察お願いします"
                else:
                    ai_main_comment = "特記すべき高度な異常所見は検出されませんでしたが、一部パラメータに変化が見られます"

                # 補足として過大評価の可能性（これは最優先とは独立して表示）
                if form["tav"] < 25 and 500 <= form["fv"] <= 1000:
                    ai_supplement = "TAVが非常に低く、FVは正常範囲 → 上腕動脈径が大きいため、過大評価の可能性があります"

                st.subheader("🧠 AI診断コメント")
                st.info(ai_main_comment)
                if ai_supplement:
                    st.info(ai_supplement)

    note = st.text_area("備考（自由記述）", placeholder="観察メモや特記事項などがあれば記入")

    with st.expander("📌 追加情報を表示"):
        TAVR = tav / tamv if tamv != 0 else 0
        RI_PI = ri / pi if pi != 0 else 0

        st.write("### TAVRの算出")
        st.write(f"TAVR: {TAVR:.2f}")
        st.write("### RI/PI の算出")
        st.write(f"RI/PI: {RI_PI:.2f}")

        st.write("### 波形分類")
        st.markdown("""
        - Ⅰ・Ⅱ型：シャント機能は問題なし  
        - Ⅲ型：50％程度の狭窄があるため精査  
        - Ⅳ型：VAIVT提案念頭に精査  
        - Ⅴ型：シャント閉塞の可能性大
        """)

        st.write("### 追加コメント")
        st.markdown("吻合部付近に2.0mmを超える分岐血管がある場合は遮断試験を行ってください")
        st.write("### 補足コメント")
        st.markdown("この補足は評価に必要な周辺知識を補完するものです。※検査時の注意点などをここにまとめられます")

    if st.button("記録を保存"):
        if name and name.strip():
            now = datetime.combine(date_selected, datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
            comment_joined = "; ".join([c[1] for c in comments])
            access_code = st.session_state.generated_access_code
            st.write("🔑 現在のアクセスコード:", access_code)

            try:
                prev = supabase.table("shunt_records").select("anon_id").eq("name", name).order("date", desc=True).limit(1).execute()
                anon_id = prev.data[0]['anon_id'] if prev.data else str(uuid.uuid4())[:8]
                supabase.table("shunt_records").insert({
                    "anon_id": anon_id,
                    "name": name,
                    "date": now,
                    "FV": fv,
                    "RI": ri,
                    "PI": pi,
                    "TAV": tav,
                    "TAMV": tamv,
                    "PSV": psv,
                    "EDV": edv,
                    "score": score,
                    "comment": comment_joined,
                    "tag": tag,
                    "note": note,
                    "va_type": va_type,
                    "access_code": access_code
                }).execute()
                st.success("記録が保存されました。")
            except Exception as e:
                st.error(f"保存中にエラーが発生しました: {e}")
        else:
            st.warning("氏名を入力してください（匿名可・本名以外でOK）")
            
if st.session_state.authenticated:
    if page == "記録一覧とグラフ":
        st.title("📊 記録の一覧と経時変化グラフ")

        try:
            access_code = st.session_state.generated_access_code
            response = supabase.table("shunt_records").select("*", count="exact").eq("access_code", access_code).execute()
            df = pd.DataFrame(response.data)
        except Exception as e:
            st.error(f"データの取得に失敗しました: {e}")
            st.stop()

        if df.empty:
            st.info("記録がまだありません。")
            st.stop()

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if df["date"].dt.tz is None:
            df["date"] = df["date"].dt.tz_localize("UTC")
        df["date"] = df["date"].dt.tz_convert("Asia/Tokyo")
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df["date_short"] = df["date"].dt.strftime("%Y-%m-%d")

        with st.container(border=True):
            names = df["name"].dropna().unique().tolist()
            selected_name = st.selectbox("氏名を選択", names)
            df_filtered = df[df["name"] == selected_name].copy()

            st.subheader("🗓 検査期間を選択")
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("開始日", value=df_filtered["date"].min().date())
            with col2:
                end_date = st.date_input("終了日", value=df_filtered["date"].max().date())

            df_filtered = df_filtered[(df_filtered["date"].dt.date >= start_date) & (df_filtered["date"].dt.date <= end_date)]

            if "show_record_list" not in st.session_state:
                st.session_state.show_record_list = False

            if st.button("記録一覧を表示 / 非表示"):
                st.session_state.show_record_list = not st.session_state.show_record_list

            if st.session_state.show_record_list:
                st.write(f"### {selected_name} の記録一覧")
                df_display = df_filtered.drop(columns=["created_at"], errors="ignore")
                st.dataframe(df_display.sort_values("date", ascending=False))

            st.subheader("✏️ 記録を修正する")
            if "edit_mode" not in st.session_state:
                st.session_state.edit_mode = False

            if st.button("記録を修正する"):
                st.session_state.edit_mode = True

        if st.session_state.edit_mode:
            st.write("どの記録を修正しますか？")
            record_options = df_filtered.sort_values("date", ascending=False)["date_str"].tolist()
            selected_date = st.selectbox("修正対象の記録日時", record_options)
            selected_row = df_filtered[df_filtered["date_str"] == selected_date].iloc[0]

            st.write("修正内容を入力してください：")
            fv = st.number_input("FV（血流量, ml/min）", value=float(selected_row["FV"]), min_value=0.0)
            ri = st.number_input("RI（抵抗指数）", value=float(selected_row["RI"]), min_value=0.0)
            pi = st.number_input("PI（脈波指数）", value=float(selected_row["PI"]), min_value=0.0)
            tav = st.number_input("TAV（時間平均流速, cm/s）", value=float(selected_row["TAV"]), min_value=0.0)
            tamv = st.number_input("TAMV（時間平均最大速度, cm/s）", value=float(selected_row["TAMV"]), min_value=0.0)
            psv = st.number_input("PSV（収縮期最大速度, cm/s）", value=float(selected_row["PSV"]), min_value=0.0)
            edv = st.number_input("EDV（拡張期末速度, cm/s）", value=float(selected_row["EDV"]), min_value=0.0)
            note = st.text_area("備考（自由記述）", value=selected_row.get("note", ""))

            if st.button("修正を確定する"):
                try:
                    supabase.table("shunt_records").update({
                        "FV": fv,
                        "RI": ri,
                        "PI": pi,
                        "TAV": tav,
                        "TAMV": tamv,
                        "PSV": psv,
                        "EDV": edv,
                        "note": note
                    }).eq("id", selected_row["id"]).execute()
                    st.success("修正が完了しました。")
                    st.session_state.edit_mode = False
                    st.rerun()
                except Exception as e:
                    st.error(f"修正に失敗しました: {e}")

        selected_record = df_filtered.sort_values("date", ascending=False).iloc[0]

        with st.container(border=True):
            st.subheader("🧠 評価チャート")
            st.caption("※最新の検査値を表示")
            period = st.selectbox("表示期間", ["全期間", "半年", "1年", "3年"])

            left, right = st.columns([1, 2])
            thresholds = {"TAV": 34.5, "RI": 0.68, "PI": 1.3, "EDV": 40.4}
            directions = {"TAV": "Above", "RI": "Above", "PI": "Above", "EDV": "Below"}
            eval_params = ["TAV", "RI", "PI", "EDV"]

            with left:
                for param in eval_params:
                    val = selected_record[param]
                    base = thresholds[param]
                    direction = directions[param]
                    fig, ax = plt.subplots(figsize=(4, 1.5))
                    if direction == "Below":
                        ax.axvspan(0, base * 0.9, color='red', alpha=0.2)
                        ax.axvspan(base * 0.9, base, color='yellow', alpha=0.2)
                        ax.axvspan(base, base * 2, color='blue', alpha=0.1)
                    else:
                        ax.axvspan(0, base, color='blue', alpha=0.1)
                        ax.axvspan(base, base * 1.1, color='yellow', alpha=0.2)
                        ax.axvspan(base * 1.1, base * 2, color='red', alpha=0.2)
                    ax.scatter(val, 0, color='red', s=100)
                    ax.set_xlim(0, base * 2)
                    ax.set_title(f"{param} Evaluation")
                    st.pyplot(fig)

                st.caption("Red: Abnormal / Yellow: Near Cutoff / Blue: Normal")

            with right:
                with st.expander("📈 経時変化グラフを表示"):
                    time_filtered = df_filtered.copy()
                    now = pd.Timestamp.now(tz="Asia/Tokyo")
                    if period != "全期間":
                        months = {"半年": 6, "1年": 12, "3年": 36}[period]
                        time_filtered["date_obj"] = pd.to_datetime(time_filtered["date"])
                        start_date = now - pd.DateOffset(months=months)
                        time_filtered = time_filtered[time_filtered["date_obj"] >= start_date]

                    all_metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
                    selected_metrics = st.multiselect("表示する項目を選択", all_metrics, default=all_metrics)
                    col1, col2 = st.columns(2)
                    for i, metric in enumerate(selected_metrics):
                        with (col1 if i % 2 == 0 else col2):
                            fig2, ax2 = plt.subplots(figsize=(5, 2.5))
                            ax2.plot(time_filtered["date_short"], time_filtered[metric], marker="o")
                            ax2.set_title(f"{metric} Trend")
                            ax2.set_xlabel("Date")
                            ax2.set_ylabel(metric)
                            ax2.grid(True)
                            ax2.set_xticks(time_filtered["date_short"])
                            ax2.set_xticklabels(time_filtered["date_short"], rotation=45, ha='right')
                            st.pyplot(fig2)

            st.subheader("🔍 自動評価結果")
            score = 0
            comments = []
            if selected_record["TAV"] <= 34.5:
                score += 1
                comments.append(("warning", "TAVが34.5 cm/s以下 → 低血流が疑われる"))
            if selected_record["RI"] >= 0.68:
                score += 1
                comments.append(("warning", "RIが0.68以上 → 高抵抗が疑われる"))
            if selected_record["PI"] >= 1.3:
                score += 1
                comments.append(("warning", "PIが1.3以上 → 脈波指数が高い"))
            if selected_record["EDV"] <= 40.4:
                score += 1
                comments.append(("warning", "EDVが40.4 cm/s以下 → 拡張期血流速度が低い"))

            st.write(f"評価スコア: {score} / 4")
            if score == 0:
                st.success("🟢 正常：経過観察が推奨されます")
            elif score in [1, 2]:
                st.warning("🟡 要注意：追加評価が必要です")
            else:
                st.error("🔴 高リスク：専門的な評価が必要です")

            if comments:
                st.write("### 評価コメント")
                for level, comment in comments:
                    if level == "warning":
                        st.warning(f"- {comment}")
                    else:
                        st.write(f"- {comment}")

            st.subheader("📝 所見コメント入力")
            comment = st.selectbox("所見コメントを選択", ["透析後に評価", "次回透析日に評価", "経過観察", "VAIVT提案"])
            followup_date = st.date_input("次回検査日")

            if st.button("この所見を保存"):
                try:
                    now_jst = pd.Timestamp.now(tz="Asia/Tokyo")
                    supabase.table("followups").insert({
                        "name": selected_name,
                        "comment": comment,
                        "followup_at": followup_date.strftime('%Y-%m-%d'),
                        "created_at": now_jst.strftime('%Y-%m-%d %H:%M:%S'),
                        "access_code": access_code
                    }).execute()
                    st.success("保存しました。")
                except Exception as e:
                    st.error(f"保存エラー: {e}")
                
if st.session_state.authenticated and page == "患者管理":
    st.title("患者管理リスト")

    try:
        access_code = st.session_state.generated_access_code
        response = supabase.table("shunt_records").select("*").eq("access_code", access_code).execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        df = pd.DataFrame()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        try:
            df["date"] = df["date"].dt.tz_localize("UTC")
        except TypeError:
            df["date"] = df["date"].dt.tz_convert("UTC")
        df["date"] = df["date"].dt.tz_convert("Asia/Tokyo")
        df["date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        name_counts = df.groupby("name")["id"].count().reset_index().rename(columns={"id": "記録数"})
    else:
        st.info("現在記録されている患者はいません。")
        name_counts = pd.DataFrame()

    if st.button("患者一覧を表示 / 非表示", key="toggle_names"):
        st.session_state.show_patient_list = not st.session_state.get("show_patient_list", False)

    if st.session_state.get("show_patient_list", False) and not name_counts.empty:
        st.dataframe(name_counts)

    if not name_counts.empty:
        selected_name = st.selectbox("患者氏名を選択", name_counts["name"].unique())
        patient_data = df[df["name"] == selected_name].sort_values(by="date", ascending=True)

        if st.button("この患者の記録を表示 / 非表示", key="toggle_patient_data"):
            st.session_state.show_patient_data = not st.session_state.get("show_patient_data", False)

        if st.session_state.get("show_patient_data", False):
            with st.container():
                st.markdown("### 検査日で絞り込み")
                if not patient_data["date"].isnull().all():
                    min_date = pd.to_datetime(patient_data["date"]).min().date()
                    max_date = pd.to_datetime(patient_data["date"]).max().date()

                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input("開始日を選択", value=min_date, min_value=min_date, max_value=max_date)
                    with col2:
                        end_date = st.date_input("終了日を選択", value=max_date, min_value=min_date, max_value=max_date)

                    if start_date > end_date:
                        st.error("開始日は終了日より前に設定してください。")
                    else:
                        patient_data = patient_data[
                            (pd.to_datetime(patient_data["date"]).dt.date >= start_date) &
                            (pd.to_datetime(patient_data["date"]).dt.date <= end_date)
                        ]
                else:
                    st.warning("検査日が存在しないため、日付による絞り込みはできません。")

                columns = ["id", "name", "date", "va_type", "FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV", "score", "tag", "note"]
                if all(col in patient_data.columns for col in columns):
                    patient_data = patient_data[columns]
                st.write(f"### {selected_name} の記録一覧")
                st.dataframe(patient_data)

        # ▼ グラフ表示トグル（ラベル固定に変更）
        if st.button("この患者のグラフを表示 / 非表示", key="toggle_graph_display"):
            st.session_state.show_graph = not st.session_state.get("show_graph", False)

        if st.session_state.get("show_graph", False):
            date_range = st.selectbox("グラフの期間を選択", ["全期間", "直近半年", "直近1年", "直近3年", "直近5年"], index=0)
            now = pd.Timestamp.now()
            filtered_data = patient_data.copy()
            if date_range != "全期間":
                if date_range == "直近半年":
                    cutoff = now - pd.DateOffset(months=6)
                elif date_range == "直近1年":
                    cutoff = now - pd.DateOffset(years=1)
                elif date_range == "直近3年":
                    cutoff = now - pd.DateOffset(years=3)
                elif date_range == "直近5年":
                    cutoff = now - pd.DateOffset(years=5)
                cutoff = pd.to_datetime(cutoff)
                filtered_data = filtered_data[pd.to_datetime(filtered_data["date"]) >= cutoff]

            metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
            col1, col2 = st.columns(2)
            for i, metric in enumerate(metrics):
                with (col1 if i % 2 == 0 else col2):
                    fig, ax = plt.subplots(figsize=(5, 2.5))
                    ax.plot(pd.to_datetime(filtered_data["date"]), filtered_data[metric], marker="o")
                    ax.set_title(f"{metric} Trend")
                    ax.set_xlabel("Date")
                    ax.set_ylabel(metric)
                    ax.grid(True)
                    ax.set_xticks(pd.to_datetime(filtered_data["date"]))
                    ax.set_xticklabels(pd.to_datetime(filtered_data["date"]).dt.strftime('%Y-%m-%d'), rotation=45, ha='right')
                    st.pyplot(fig)

        # ▼ 氏名修正フォーム（トグル + 確認）
        if st.button("氏名を修正するフォームを表示 / 非表示", key="toggle_edit_form"):
            st.session_state.show_edit_form = not st.session_state.get("show_edit_form", False)

        if st.session_state.get("show_edit_form", False):
            st.write("### 氏名の修正（氏名単位）")
            unique_names = df["name"].dropna().unique().tolist()
            edit_target_name = st.selectbox("修正対象の氏名", unique_names, key="edit_select")
            new_name = st.text_input("新しい氏名", value=edit_target_name, key="new_name_input")

            if "confirm_edit" not in st.session_state:
                st.session_state.confirm_edit = False

            if st.button("氏名を更新"):
                if edit_target_name == new_name:
                    st.warning("新しい氏名が変更前と同じです。")
                else:
                    st.session_state.confirm_edit = True

            if st.session_state.confirm_edit:
                if st.button("⚠ 本当に氏名を更新しますか？（再クリックで実行）"):
                    supabase.table("shunt_records") \
                        .update({"name": new_name}) \
                        .eq("name", edit_target_name) \
                        .eq("access_code", st.session_state.generated_access_code) \
                        .execute()
                    st.success("氏名を更新しました。ページを再読み込みしてください。")
                    st.session_state.confirm_edit = False

        # ▼ 記録削除フォーム（トグル + 確認）
        if st.button("記録を削除するフォームを表示 / 非表示", key="toggle_delete_form"):
            st.session_state.show_delete_form = not st.session_state.get("show_delete_form", False)

        if st.session_state.get("show_delete_form", False):
            st.write("### 記録の削除（氏名単位）")
            unique_names = df["name"].dropna().unique().tolist()
            delete_target_name = st.selectbox("削除する氏名", unique_names, key="delete_select")

            if "confirm_delete" not in st.session_state:
                st.session_state.confirm_delete = False

            if st.button("記録を削除"):
                st.session_state.confirm_delete = True

            if st.session_state.confirm_delete:
                if st.button("⚠ 本当に削除しますか？（再クリックで実行）"):
                    supabase.table("shunt_records") \
                        .delete() \
                        .eq("name", delete_target_name) \
                        .eq("access_code", st.session_state.generated_access_code) \
                        .execute()
                    st.success("記録を削除しました。ページを再読み込みしてください。")
                    st.session_state.confirm_delete = False



# 箱ひげ図（中央値・外れ値強調・N数表示）関数
def draw_boxplot_with_median_outliers(data, metric, category_col):
    fig, ax = plt.subplots(figsize=(6, 4))
    sns.boxplot(x=category_col, y=metric, data=data, ax=ax,
                medianprops={"color": "black", "linewidth": 2},
                flierprops=dict(marker='o', markerfacecolor='red', markersize=6, linestyle='none'))

    # N数（サンプル数）をラベルとして追加
    group_counts = data[category_col].value_counts().to_dict()
    xtick_labels = [f"{label.get_text()}\n(n={group_counts.get(label.get_text(), 0)})" for label in ax.get_xticklabels()]
    ax.set_xticklabels(xtick_labels)

    ax.set_title(f"{metric} の比較")
    ax.set_xlabel("評価カテゴリ")
    ax.set_ylabel(metric)
    plt.tight_layout()
    return fig

# ページ：患者データ一覧
if st.session_state.authenticated and page == "患者データ一覧":
    st.title("患者データ一覧（ボタン形式 + 特記事項比較）")

    try:
        access_code = st.session_state.generated_access_code
        response = supabase.table("shunt_records").select("*").eq("access_code", access_code).execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"データ取得に失敗しました: {e}")
        df = pd.DataFrame()

    if df.empty:
        st.info("患者データが存在しません。")
    else:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df["date"] = df["date"].dt.tz_convert("Asia/Tokyo")
        df["date_display"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")

        unique_names = df["name"].dropna().unique().tolist()

        if 'show_patient_selector' not in st.session_state:
            st.session_state.show_patient_selector = False

        if st.button("患者記録をみる"):
            st.session_state.show_patient_selector = not st.session_state.show_patient_selector

        if st.session_state.show_patient_selector:
            selected_name = st.selectbox("患者を選択", unique_names, key="select_patient")
            patient_data = df[df["name"] == selected_name].sort_values(by="date")

            if not patient_data.empty:
                min_date = patient_data["date"].min().date()
                max_date = patient_data["date"].max().date()

                with st.form("filter_form"):
                    selected_range = st.date_input("記録日の範囲で絞り込み", [min_date, max_date])
                    submitted = st.form_submit_button("この期間の記録を表示")

                if submitted:
                    st.session_state.show_filtered_data = True
                    st.session_state.selected_range = selected_range

                if st.session_state.get("show_filtered_data", False):
                    start_date, end_date = st.session_state.selected_range
                    start_dt = pd.Timestamp(start_date).tz_localize("Asia/Tokyo")
                    end_dt = pd.Timestamp(end_date).tz_localize("Asia/Tokyo") + pd.Timedelta(days=1)

                    filtered_data = patient_data[(patient_data["date"] >= start_dt) & (patient_data["date"] < end_dt)]

                    with st.expander(f"{selected_name} の記録一覧（表示/非表示）"):
                        if filtered_data.empty:
                            st.warning("選択された日付には検査記録がありません。")
                        else:
                            display_columns = ["id", "name", "date", "va_type", "FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV", "score", "tag", "note"]
                            display_data = filtered_data.copy()
                            display_data["date"] = display_data["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
                            st.dataframe(display_data[display_columns], height=200)

        st.markdown("---")
        st.subheader("📊 特記事項カテゴリでの比較")
        categories = df["tag"].dropna().unique().tolist()
        va_types = df["va_type"].dropna().unique().tolist()
        all_categories = sorted(set(categories + va_types))
        selected_category = st.selectbox("特記事項またはVAの種類を選択して記録を表示", all_categories, key="cat_view")

        if selected_category in categories:
            cat_data = df[df["tag"] == selected_category]
        else:
            cat_data = df[df["va_type"] == selected_category]

        display_cat = cat_data.copy()
        display_cat["date"] = cat_data["date"].dt.strftime("%Y-%m-%d %H:%M:%S")

        with st.expander(f"{selected_category} の記録一覧（表示/非表示）"):
            st.dataframe(display_cat)

        compare_categories = st.multiselect("比較したいカテゴリを選択（2つまで）", all_categories)
        if len(compare_categories) == 2:
            compare_data = df[
                (df["tag"].isin(compare_categories)) | (df["va_type"].isin(compare_categories))
            ].copy()

            compare_data["category_label"] = None
            compare_data.loc[
                (compare_data["tag"] == compare_categories[0]) | (compare_data["va_type"] == compare_categories[0]),
                "category_label"
            ] = compare_categories[0]
            compare_data.loc[
                (compare_data["tag"] == compare_categories[1]) | (compare_data["va_type"] == compare_categories[1]),
                "category_label"
            ] = compare_categories[1]

            st.markdown("#### ※ Mann-Whitney U Test")
            metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
            p_results = {"Metric": [], "p-value": []}
            for metric in metrics:
                group1 = compare_data[compare_data["category_label"] == compare_categories[0]][metric]
                group2 = compare_data[compare_data["category_label"] == compare_categories[1]][metric]
                if len(group1.dropna()) > 0 and len(group2.dropna()) > 0:
                    stat, p = mannwhitneyu(group1, group2, alternative='two-sided')
                    p_results["Metric"].append(metric)
                    p_results["p-value"].append(round(p, 4))
            st.dataframe(pd.DataFrame(p_results), height=150)

            st.markdown("---")
            st.subheader("📊 Boxplot Comparison")
            col1, col2 = st.columns(2)
            for i, metric in enumerate(metrics):
                with (col1 if i % 2 == 0 else col2):
                    plot_data = compare_data[["category_label", metric]].dropna()
                    if plot_data["category_label"].nunique() == 2:
                        fig, ax = plt.subplots(figsize=(5, 3))
                        sns.boxplot(x="category_label", y=metric, data=plot_data, ax=ax,
                                    medianprops={"color": "black", "linewidth": 2},
                                    flierprops=dict(marker='o', markerfacecolor='red', markersize=6, linestyle='none'))
                        group_counts = plot_data["category_label"].value_counts().to_dict()
                        xtick_labels = [f"{label.get_text()}\n(n={group_counts.get(label.get_text(), 0)})" for label in ax.get_xticklabels()]
                        ax.set_xticklabels(xtick_labels)
                        ax.set_title(f"{metric} Comparison")
                        ax.set_xlabel("Category")
                        ax.set_ylabel(metric)
                        plt.tight_layout()
                        st.pyplot(fig)
                    else:
                        st.warning(f"{metric} に関して比較可能なデータがありません。")
