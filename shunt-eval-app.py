import streamlit as st
st.set_page_config(page_title="シャント機能評価", layout="wide")

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import datetime
import uuid
import os
import sqlite3
import seaborn as sns
import pytz
from scipy.stats import mannwhitneyu

from supabase import create_client, Client
from dotenv import load_dotenv

# --- スタイル設定 ---
matplotlib.rcParams['font.family'] = 'MS Gothic'

# --- シミュレーション用の定数（復元済み） ---
baseline_FV = 500
baseline_RI = 0.6
baseline_diameter = 5.0

coefficients = {
    "PSV": 0.5,
    "EDV": 0.2,
    "TAV": 0.35,
    "TAMV": 0.4
}

# --- シミュレーション用の関数 ---
def calculate_parameter(FV, RI, diameter, coef):
    return coef * FV / (RI * diameter)

def calculate_tavr(tav, tamv):
    return tav / tamv if tamv != 0 else 0

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
if not st.session_state.authenticated:
    st.sidebar.empty()
    st.title("🔐 シャント機能評価ツール - ログイン")

    user_type = st.radio("ご利用は初めてですか？", ["はい（新規）", "いいえ（既存ユーザー）"])
    st.session_state.new_user = user_type == "はい（新規）"

    password_input = st.text_input("4桁のパスワードを入力してください", type="password")

    if st.session_state.new_user:
        if len(password_input) == 4 and password_input.isdigit():
            if st.button("登録する"):
                access_code = register_user(password_input)
                if access_code:
                    st.session_state.authenticated = True
                    st.session_state.password = password_input
                    st.session_state.generated_access_code = access_code
                    st.success(f"登録完了！アクセスコード: `{access_code}`")
                    st.code(access_code)
                else:
                    st.warning("すでに登録されているパスワードです。他のものを使用してください。")
    else:
        access_code = st.text_input("アクセスコードを入力してください")
        if len(password_input) == 4 and password_input.isdigit() and access_code:
            user = authenticate_user(password_input, access_code)
            if user:
                st.success("ログイン成功！")
                st.session_state.authenticated = True
                st.session_state.password = password_input
                st.rerun()
            else:
                st.error("パスワードまたはアクセスコードが正しくありません")

    st.stop()

# --- ログイン済みユーザーの処理 ---
if st.session_state.authenticated:
    with st.sidebar:
        st.title("ページ選択")
        st.session_state.page = st.radio("", ["ToDoリスト", "シミュレーションツール", "評価フォーム", "記録一覧とグラフ", "患者管理", "患者データ一覧"], key="main_page_selector")

        if st.button("ログアウト"):
            st.session_state.authenticated = False
            st.session_state.new_user = None
            st.session_state.page = ""
            st.rerun()

    page = st.session_state.page
    st.write(f"ようこそ。現在のページ：{page}")

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

 # --- ページ：ToDoリスト ---
    if page == "ToDoリスト":
        st.header("📋 ToDoリスト")

        # --- 本日の followups（検査予定）取得 ---
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

        # --- 本日の検査対象者表示 ---
        st.subheader("🔔 本日の検査予定")
        if not matches.empty:
            for _, row in matches.iterrows():
                st.write(f"🧑‍⚕️ {row['name']} さん - コメント: {row['comment']}")
        else:
            st.info("本日の検査予定はありません。")

        # --- カレンダーに紐づいたメモ登録 ---
        st.subheader("🗓 カレンダーでタスクを管理")
        task_date = st.date_input("タスク日を選択")
        task_text = st.text_input("タスク内容を入力")
        if st.button("追加"):
            try:
                supabase.table("tasks").insert({
                    "date": task_date.strftime('%Y-%m-%d'),
                    "content": task_text,
                    "access_code": st.session_state.generated_access_code
                }).execute()
                st.success("タスクを追加しました")
            except Exception as e:
                st.error(f"タスクの追加に失敗しました: {e}")

        # --- 登録済みタスク一覧表示 ---
        st.subheader("📅 登録済みタスク一覧")
        try:
            task_response = supabase.table("tasks") \
                .select("date, content") \
                .eq("access_code", st.session_state.generated_access_code) \
                .order("date", desc=False) \
                .execute()
            task_df = pd.DataFrame(task_response.data)
            if task_df.empty:
                st.info("現在タスクは登録されていません。")
            else:
                for _, row in task_df.iterrows():
                    st.write(f"🗓 {row['date']} - 📌 {row['content']}")
        except Exception:
            st.info("本日にタスクはありません。")

# --- シミュレーションツール ページ ---
if st.session_state.authenticated and page == "シミュレーションツール":
    st.title("シャント機能評価シミュレーションツール")
    st.markdown("---")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        FV = st.slider("血流量 FV (ml/min)", min_value=100, max_value=2000, value=int(baseline_FV), step=10)
        RI = st.slider("抵抗指数 RI", min_value=0.4, max_value=1.0, value=float(baseline_RI), step=0.01)
        diameter = st.slider("血管幅 (mm)", min_value=3.0, max_value=7.0, value=baseline_diameter, step=0.1)

    # パラメータ計算
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

# --- 評価フォーム（Supabase 対応） ---
if page == "評価フォーム":
    st.title("シャント機能評価フォーム")

    try:
        df_names = supabase.table("shunt_records").select("name").neq("name", "").execute()
        name_list = list({entry['name'] for entry in df_names.data})
    except Exception as e:
        st.error(f"名前一覧の取得エラー: {e}")
        name_list = []

    date_selected = st.date_input("記録日を選択", value=datetime.date.today())

    name_option = st.radio("患者名の入力方法", ["新規入力", "過去から選択"])
    if name_option == "新規入力":
        name = st.text_input("氏名（任意）※本名では記入しないでください")
    else:
        name = st.selectbox("過去の患者名から選択", name_list)

    tag = st.selectbox("特記事項", ["術前評価", "術後評価", "定期評価", "VAIVT前評価", "VAIVT後評価"])
    va_type = st.selectbox("VAの種類", ["AVF", "AVG", "動脈表在化"], index=0)

    fv = st.number_input("FV（血流量, ml/min）", min_value=0.0, value=400.0)
    ri = st.number_input("RI（抵抗指数）", min_value=0.0, value=0.6)
    pi = st.number_input("PI（脈波指数）", min_value=0.0, value=1.2)
    tav = st.number_input("TAV（時間平均流速, cm/s）", min_value=0.0, value=60.0)
    tamv = st.number_input("TAMV（時間平均最大速度, cm/s）", min_value=0.0, value=100.0)
    psv = st.number_input("PSV（収縮期最大速度, cm/s）", min_value=0.0, value=120.0)
    edv = st.number_input("EDV（拡張期末速度, cm/s）", min_value=0.0, value=50.0)

    # --- 評価スコアの計算 ---
    score = 0
    comments = []
    if tav <= 34.5:
        score += 1
        comments.append("TAVが34.5 cm/s以下 → 低血流が疑われる")
    if ri >= 0.68:
        score += 1
        comments.append("RIが0.68以上 → 高抵抗が疑われる")
    if pi >= 1.3:
        score += 1
        comments.append("PIが1.3以上 → 脈波指数が高い")
    if edv <= 40.4:
        score += 1
        comments.append("EDVが40.4 cm/s以下 → 拡張期血流速度が低い")

    st.write("### 評価結果")
    st.write(f"評価スコア: {score} / 4")
    if score == 0:
        st.success("シャント機能は正常です。経過観察が推奨されます。")
    elif score in [1, 2]:
        st.warning("シャント機能は要注意です。追加評価が必要です。")
    else:
        st.error("シャント不全のリスクが高いです。専門的な評価が必要です。")

    if comments:
        st.write("### 評価コメント")
        for comment in comments:
            st.write(f"- {comment}")

    st.write("### 波形分類")
    st.markdown("""
    - Ⅰ・Ⅱ型：シャント機能は問題なし
    - Ⅲ型：50％程度の狭窄があるため精査
    - Ⅳ型：VAIVT提案念頭に精査
    - Ⅴ型：シャント閉塞の可能性大
    """)

    with st.expander("📌 補足説明を表示"):
        st.markdown("""
        - Ⅰ型：抵抗が低く、血流も良好
        - Ⅱ型：血流に若干の乱れ
        - Ⅲ型：狭窄の兆候あり
        - Ⅳ型：高度狭窄
        - Ⅴ型：血流停止の可能性
        """)

    with st.expander("透析中の状態評価を入力"):
        g_size = st.selectbox("穿刺針のG数は？", ["15G", "16G", "17G"])
        blood_flow_setting = st.number_input("設定血液流量 (ml/min)", min_value=0.0)
        issue_de = st.radio("脱血不良がありますか？", ["いいえ", "はい"])
        de_type = st.radio("穿刺方向は？", ["順行性穿刺", "逆行性穿刺"]) if issue_de == "はい" else ""

        issue_pressure = st.radio("静脈圧の上昇はありますか？", ["いいえ", "はい"])
        static_pressure = mean_pressure = iap_ratio = 0.0
        if issue_pressure == "はい" and va_type == "AVG":
            static_pressure = st.number_input("静的静脈圧 (mmHg)", min_value=0.0)
            mean_pressure = st.number_input("平均血圧 (mmHg)", min_value=0.0)
            iap_ratio = static_pressure / mean_pressure if mean_pressure else 0.0

        recirculation = st.number_input("再循環はありますか？ (％)", min_value=0.0, max_value=100.0)

        if st.button("透析評価"):
            if issue_de == "はい":
                st.info("次回逆行性穿刺でお願いします" if de_type == "順行性穿刺" else "A穿刺部より末梢に狭窄が疑われます")
            if issue_pressure == "はい":
                if va_type == "AVF":
                    st.info("V穿刺部より中枢に狭窄が疑われます")
                elif static_pressure >= 40 and iap_ratio > 0.40:
                    st.info("G-Vか中枢の狭窄が疑われます")
            if (va_type == "AVF" and recirculation > 5) or (va_type == "AVG" and recirculation > 10):
                st.info("穿刺部の再考、エコー検査を推奨します")

    note = st.text_area("備考（自由記述）", placeholder="観察メモや特記事項などがあれば記入")

    with st.expander("📌 追加情報を表示"):
        TAVR = tav / tamv if tamv != 0 else 0
        RI_PI = ri / pi if pi != 0 else 0
        st.write("### TAVRの算出")
        st.write(f"TAVR: {TAVR:.2f}")
        st.write("### RI/PI の算出")
        st.write(f"RI/PI: {RI_PI:.2f}")
        st.write("### 追加コメント")
        st.markdown("吻合部付近に2.0mmを超える分岐血管がある場合は遮断試験を行ってください")
        st.write("### 補足コメント")
        st.markdown("この補足は評価に必要な周辺知識を補完するものです。※検査時の注意点などをここにまとめられます")

    if st.button("記録を保存"):
    if name and name.strip():
        now = datetime.datetime.combine(date_selected, datetime.datetime.now().time()).strftime("%Y-%m-%d %H:%M:%S")
        comment_joined = "; ".join(comments)
        try:
            prev = supabase.table("shunt_records").select("anon_id") \
                .eq("name", name).order("date", desc=True).limit(1).execute()
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
                "access_code": st.session_state.generated_access_code  # 👈 Supabase RLS対応
            }).execute()
            st.success("記録が保存されました。")
        except Exception as e:
            st.error(f"保存中にエラーが発生しました: {e}")
    else:
        st.warning("氏名を入力してください（匿名可・本名以外でOK）")

# 記録一覧とグラフページでの経時変化グラフ使用例（Supabase 対応）
if page == "記録一覧とグラフ":
    st.title("記録の一覧と経時変化グラフ")
    try:
        response = supabase.table("shunt_records").select("*").execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"データの取得に失敗しました: {e}")
        st.stop()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")
        df["date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")

        filtered_names = df["name"].dropna().unique().tolist()
        if "" in filtered_names:
            filtered_names.remove("")
        selected_name = st.selectbox("表示する氏名を選択", filtered_names)
        df_filtered = df[df["name"] == selected_name]

        columns = ["id", "name", "date", "va_type", "FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV", "score", "tag", "note"]
        if all(col in df_filtered.columns for col in columns):
            df_filtered = df_filtered[columns].sort_values(by="date", ascending=True)

        if st.button("記録一覧を表示 / 非表示", key="toggle_record_list"):
            st.session_state.show_record_list = not st.session_state.get("show_record_list", False)
        if st.session_state.get("show_record_list", True):
            st.write(f"### {selected_name} の記録一覧")
            st.dataframe(df_filtered)

        st.markdown("検査日時を選択")
        selectable_datetimes = df_filtered["date"].tolist()
        selected_datetime_str = st.selectbox("検査日時を選択", selectable_datetimes)
        selected_records = df_filtered[df_filtered["date"] == selected_datetime_str]

        if not selected_records.empty:
            selected_record = selected_records.iloc[-1]

            if st.button("レポート出力を表示 / 非表示", key="toggle_report"):
                st.session_state.show_report = not st.session_state.get("show_report", False)

            if st.session_state.get("show_report", False):
                latest = selected_record
                st.subheader("📄 レポート")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Patient Name**: {latest['name']}")
                    st.markdown(f"**Generated At**: {get_japan_now().strftime('%Y-%m-%d %H:%M:%S')}")

                    report_df = pd.DataFrame({
                        "Parameter": ["TAV", "RI", "PI", "EDV"],
                        "Value": [latest["TAV"], latest["RI"], latest["PI"], latest["EDV"]],
                        "Threshold": [34.5, 0.68, 1.3, 40.4],
                        "Direction": ["Below", "Above", "Above", "Below"]
                    })
                    st.dataframe(report_df, use_container_width=True)

                    for _, row in report_df.iterrows():
                        param, val, base, direction = row
                        if param == "RI":
                            xlim = (0, 1.0); xticks = np.arange(0, 1.1, 0.1)
                        elif param == "PI":
                            xlim = (0, 5.0); xticks = np.arange(0, 5.5, 0.5)
                        else:
                            xlim = (0, max(1.5 * val, base * 1.5)); xticks = None

                        fig, ax = plt.subplots(figsize=(5, 1.8))
                        if direction == "Below":
                            ax.axvspan(0, base * 0.9, color='red', alpha=0.2)
                            ax.axvspan(base * 0.9, base, color='yellow', alpha=0.2)
                            ax.axvspan(base, xlim[1], color='blue', alpha=0.1)
                        else:
                            ax.axvspan(0, base, color='blue', alpha=0.1)
                            ax.axvspan(base, base * 1.1, color='yellow', alpha=0.2)
                            ax.axvspan(base * 1.1, xlim[1], color='red', alpha=0.2)

                        ax.scatter(val, 0, color='red', s=100, zorder=5)
                        ax.set_xlim(xlim)
                        if xticks is not None:
                            ax.set_xticks(xticks)
                        ax.set_title(f"{param} Evaluation")
                        ax.set_xlabel("Value")
                        st.pyplot(fig)

                    st.caption("Red: Abnormal / Yellow: Near Cutoff / Blue: Normal")

                    comment = st.selectbox("所見コメントを選択", ["透析後に評価", "次回透析日に評価", "経過観察", "VAIVT提案"], key="comment_select")

                    followup_date = None
                    if comment in ["次回透析日に評価", "経過観察"]:
                        followup_date = st.date_input("次回検査日を選択", key="followup_date")

                    if st.button("この所見を保存"):
                        now_jst = pd.Timestamp.now(tz="Asia/Tokyo")
                        try:
                            supabase.table("followups").insert({
                                "name": selected_name,
                                "comment": comment,
                                "followup_at": followup_date.strftime('%Y-%m-%d') if followup_date else None,
                                "created_at": now_jst.strftime('%Y-%m-%d %H:%M:%S')
                            }).execute()
                            st.success("所見と次回検査日を保存しました。")
                        except Exception as e:
                            st.error(f"保存に失敗しました: {e}")

                with col2:
                    st.markdown("### Trend Graphs")
                    metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
                    col1, col2 = st.columns(2)
                    for i, metric in enumerate(metrics):
                        with (col1 if i % 2 == 0 else col2):
                            fig2, ax2 = plt.subplots(figsize=(5, 2.5))
                            ax2.plot(df_filtered["date"], df_filtered[metric], marker="o")
                            ax2.set_title(f"{metric} Trend")
                            ax2.set_xlabel("Date")
                            ax2.set_ylabel(metric)
                            ax2.grid(True)
                            ax2.set_xticks(df_filtered["date"])
                            ax2.set_xticklabels(df_filtered["date"], rotation=45, ha='right')
                            st.pyplot(fig2)

        if st.button("グラフ出力を表示 / 非表示", key="toggle_full_graph"):
            st.session_state.show_full_graph = not st.session_state.get("show_full_graph", False)

        if st.session_state.get("show_full_graph", False):
            metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
            col1, col2 = st.columns(2)
            for i, metric in enumerate(metrics):
                with (col1 if i % 2 == 0 else col2):
                    fig, ax = plt.subplots(figsize=(5, 2.5))
                    ax.plot(df_filtered["date"], df_filtered[metric], marker="o")
                    ax.set_title(f"{metric} Trend")
                    ax.set_xlabel("Date")
                    ax.set_ylabel(metric)
                    ax.grid(True)
                    ax.set_xticks(df_filtered["date"])
                    ax.set_xticklabels(df_filtered["date"], rotation=45, ha='right')
                    st.pyplot(fig)
    else:
        st.info("記録がまだありません。")

# ページ：患者管理
if page == "患者管理":
    st.title("患者管理リスト")
    response = supabase.table("shunt_records").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        # ✅ 日付を日本時間に変換し、表示形式を整える
        df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")
        df["date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")

        name_counts = df.groupby("name")["id"].count().reset_index().rename(columns={"id": "記録数"})

        # ▼ 患者一覧表示トグル
        if st.button("患者一覧を表示 / 非表示", key="toggle_names"):
            st.session_state.show_patient_list = not st.session_state.get("show_patient_list", False)

        if st.session_state.get("show_patient_list", False):
            st.dataframe(name_counts)

        # ▼ 氏名選択
        selected_name = st.selectbox("患者氏名を選択", name_counts["name"].unique())
        patient_data = df[df["name"] == selected_name].sort_values(by="date", ascending=True)

        # ▼ 検査日で絞り込み
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

        # ▼ 表示列の制限
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
                    supabase.table("shunt_records").update({"name": new_name}).eq("name", edit_target_name).execute()
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
                    supabase.table("shunt_records").delete().eq("name", delete_target_name).execute()
                    st.success("記録を削除しました。ページを再読み込みしてください。")
                    st.session_state.confirm_delete = False

    else:
        st.info("現在記録されている患者はいません。")

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
if page == "患者データ一覧":
    st.title("患者データ一覧（ボタン形式 + 特記事項比較）")
    response = supabase.table("shunt_records").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")
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
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                    filtered_data = patient_data[(patient_data["date"] >= start_dt) & (patient_data["date"] < end_dt)]

                    st.write(f"### {selected_name} の記録一覧")
                    if filtered_data.empty:
                        st.warning("選択された日付には検査記録がありません。")
                    else:
                        display_columns = ["id", "name", "date_display", "va_type", "FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV", "score", "tag", "note"]
                        display_data = filtered_data.copy()
                        display_data = display_data.rename(columns={"date_display": "date"})[display_columns]
                        st.dataframe(display_data, height=200)

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
        st.write(f"#### {selected_category} の記録一覧")
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
    else:
        st.info("患者データが存在しません。")
