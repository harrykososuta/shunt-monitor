import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import sqlite3
import datetime
import uuid
import os
import seaborn as sns
from scipy.stats import mannwhitneyu

# ページ選択定義（先に必要）
page = st.sidebar.radio("ページ選択", ["ログイン", "シミュレーションツール", "評価フォーム", "記録一覧とグラフ", "患者管理", "患者データ一覧"])

# セッション管理
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'password' not in st.session_state:
    st.session_state.password = ""

# SQLite データベース接続（認証用）
AUTH_DB_FILE = "auth_users.db"
auth_conn = sqlite3.connect(AUTH_DB_FILE)
auth_cursor = auth_conn.cursor()
auth_cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password TEXT UNIQUE
)''')
auth_conn.commit()

# ログアウト機能
if st.sidebar.button("ログアウト"):
    st.session_state.authenticated = False
    st.experimental_rerun()

# ログインページ
if page == "ログイン":
    st.title("🔐 シャント機能評価ツール - ログイン")

    if not st.session_state.authenticated:
        access_code = st.text_input("アクセスコードを入力してください", type="password")
        if access_code == "shunt2025":
            new_password = st.text_input("4桁のパスワードを設定または入力", type="password")
            if len(new_password) == 4 and new_password.isdigit():
                auth_cursor.execute("SELECT * FROM users WHERE password = ?", (new_password,))
                result = auth_cursor.fetchone()
                if result:
                    st.success("ログイン成功！")
                    st.session_state.authenticated = True
                    st.session_state.password = new_password
                else:
                    if st.button("このパスワードで登録"):
                        auth_cursor.execute("INSERT INTO users (password) VALUES (?)", (new_password,))
                        auth_conn.commit()
                        st.success("登録完了！次回からこのパスワードでログインできます")
                        st.session_state.authenticated = True
                        st.session_state.password = new_password
            else:
                st.info("4桁の数字でパスワードを入力してください")
        elif access_code != "":
            st.error("アクセスコードが無効です")
    else:
        st.success("すでにログイン済みです")

# ログイン後のみ許可されたページ群
if st.session_state.authenticated and page != "ログイン":

    # DBファイルをパスワードごとに分離
    user_password = st.session_state.password
    DB_FILE = f"shunt_data_{user_password}.db"
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # データベースを初期化（ユーザー別）
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
        tag TEXT
    )''')
    conn.commit()

   # 経時変化グラフ用フォーマット関数（x軸を日付のみ表示）
def format_xaxis_as_date(ax, df):
    ax.set_xticks(df['date'])
    ax.set_xticklabels(df['date'].dt.strftime('%Y-%m-%d'), rotation=45)
    return ax

# ページ設定
st.set_page_config(page_title="シャント機能評価", layout="wide")
matplotlib.rcParams['font.family'] = 'MS Gothic'

# SQLite データベースを初期化
DB_FILE = "shunt_data.db"
if not os.path.exists(DB_FILE):
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
        tag TEXT
    )''')
    conn.commit()
else:
    conn = sqlite3.connect(DB_FILE)

# 計算用定数
baseline_FV = 380
baseline_RI = 0.68
baseline_diameter = 5.0
coefficients = {
    "PSV": [37.664, 0.0619, 52.569, -1.2],
    "EDV": [69.506, 0.0305, -74.499, -0.8],
    "TAV": [43.664, 0.0298, -35.760, -0.6],
    "TAMV": [65.0, 0.0452, -30.789, -1.0]
}

def calculate_parameter(FV, RI, diameter, coeffs):
    return coeffs[0] + coeffs[1]*FV + coeffs[2]*RI + coeffs[3]*diameter

def calculate_tavr(TAV, TAMV):
    return TAV / TAMV if TAMV != 0 else 0

page = st.sidebar.radio("ページ選択", ["シミュレーションツール", "評価フォーム", "記録一覧とグラフ", "患者管理", "患者データ一覧"])

if page == "シミュレーションツール":
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
    st.write(f"PSV: {PSV:.2f} cm/s")
    st.write(f"EDV: {EDV:.2f} cm/s")
    st.write(f"PI: {PI:.2f}")
    st.write(f"TAV: {TAV:.2f} cm/s")
    st.write(f"TAMV: {TAMV:.2f} cm/s")
    st.write(f"TAVR: {TAVR:.2f}")

# ページ：評価フォーム
if page == "評価フォーム":
    st.title("シャント機能評価フォーム")
    df_names = pd.read_sql_query("SELECT DISTINCT name FROM shunt_records WHERE name != ''", conn)
    name_option = st.radio("患者名の入力方法", ["新規入力", "過去から選択"])
    if name_option == "新規入力":
        name = st.text_input("氏名（任意）※本名では記入しないでください")
    else:
        name = st.selectbox("過去の患者名から選択", df_names["name"].tolist())

    tag = st.selectbox("特記事項", ["術前評価", "術後評価", "定期評価", "VAIVT前評価", "VAIVT後評価"])

    fv = st.number_input("FV（血流量, ml/min）", min_value=0.0, value=400.0)
    ri = st.number_input("RI（抵抗指数）", min_value=0.0, value=0.6)
    pi = st.number_input("PI（脈波指数）", min_value=0.0, value=1.2)
    tav = st.number_input("TAV（時間平均流速, cm/s）", min_value=0.0, value=60.0)
    tamv = st.number_input("TAMV（時間平均最大速度, cm/s）", min_value=0.0, value=100.0)
    psv = st.number_input("PSV（収縮期最大速度, cm/s）", min_value=0.0, value=120.0)
    edv = st.number_input("EDV（拡張期末速度, cm/s）", min_value=0.0, value=50.0)

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

    TAVR = calculate_tavr(tav, tamv)
    RI_PI = ri / pi if pi != 0 else 0

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
    st.write("Ⅰ・Ⅱ型はシャント機能は問題なし")
    st.write("Ⅲ型は50％程度の狭窄があるため細かく精査")
    st.write("Ⅳ型はVAIVTを提案を念頭に精査")
    st.write("Ⅴ型はシャント閉塞している可能性が高い")

    st.write("### TAVRの算出")
    st.write(f"TAVR: {TAVR:.2f}")
    st.write("### RI/PI の算出")
    st.write(f"RI/PI: {RI_PI:.2f}")

    st.write("### 追加コメント")
    st.write("吻合部付近に2.0mmを超える分岐血管がある場合は遮断試験を行ってください")

    if st.button("記録を保存"):
        if name.strip() == "":
            st.warning("氏名を入力してください（匿名可・本名以外でOK）")
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            comment_joined = "; ".join(comments)
            cursor = conn.cursor()
            cursor.execute("SELECT anon_id FROM shunt_records WHERE name = ? ORDER BY date DESC LIMIT 1", (name,))
            result = cursor.fetchone()
            if result:
                anon_id = result[0]
            else:
                anon_id = str(uuid.uuid4())[:8]
            cursor.execute("""
                INSERT INTO shunt_records (anon_id, name, date, FV, RI, PI, TAV, TAMV, PSV, EDV, score, comment, tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (anon_id, name, now, fv, ri, pi, tav, tamv, psv, edv, score, comment_joined, tag))
            conn.commit()
            st.success("記録が保存されました。")

# 記録一覧とグラフページでの経時変化グラフ使用例
if page == "記録一覧とグラフ":
    st.title("記録の一覧と経時変化グラフ")
    df = pd.read_sql_query("SELECT * FROM shunt_records", conn)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        filtered_names = df["name"].dropna().unique().tolist()
        if "" in filtered_names:
            filtered_names.remove("")
        selected_name = st.selectbox("表示する氏名を選択", filtered_names)
        df_filtered = df[df["name"] == selected_name]
        st.write(f"### {selected_name} の記録一覧")
        st.dataframe(df_filtered)

        if st.button("レポートを出力"):
            latest = df_filtered.sort_values(by="date", ascending=False).iloc[0]
            st.subheader("📄 レポート")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**患者名**: {latest['name']}")
                st.markdown(f"**出力日**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                report_df = pd.DataFrame({
                    "パラメータ": ["TAV", "RI", "PI", "EDV"],
                    "値": [latest["TAV"], latest["RI"], latest["PI"], latest["EDV"]],
                    "基準": [34.5, 0.68, 1.3, 40.4],
                    "方向": ["以下", "以上", "以上", "以下"]
                })
                st.dataframe(report_df, use_container_width=True)

                fig_list = []

                for i, row in report_df.iterrows():
                    param = row["パラメータ"]
                    val = row["値"]
                    base = row["基準"]
                    direction = row["方向"]

                    if param == "RI":
                        xlim = (0, 1.0)
                        xticks = np.arange(0, 1.1, 0.1)
                    elif param == "PI":
                        xlim = (0, 5.0)
                        xticks = np.arange(0, 5.5, 0.5)
                    else:
                        xlim = (0, max(1.5 * val, base * 1.5))
                        xticks = None

                    fig, ax = plt.subplots(figsize=(5, 1.8))

                    if direction == "以下":
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
                    ax.set_title(f"{param} 評価")
                    ax.set_xlabel("測定値")
                    st.pyplot(fig)
                    fig_list.append(fig)

                st.caption("赤: 異常値 / 黄: カットオフ付近 / 青: 正常")

                st.markdown("### 評価コメント")
                comments = []
                if latest["TAV"] <= 34.5:
                    comments.append("TAVが34.5 cm/s以下 → 低血流が疑われる")
                if latest["RI"] >= 0.68:
                    comments.append("RIが0.68以上 → 高抵抗が疑われる")
                if latest["PI"] >= 1.3:
                    comments.append("PIが1.3以上 → 脈波指数が高い")
                if latest["EDV"] <= 40.4:
                    comments.append("EDVが40.4 cm/s以下 → 拡張期血流速度が低い")
                if comments:
                    for c in comments:
                        st.write(f"- {c}")
                else:
                    st.success("異常所見は見られません")

            with col2:
                st.markdown("### 経時変化グラフ")
                metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
                for metric in metrics:
                    fig2, ax2 = plt.subplots(figsize=(6, 2))
                    ax2.plot(df_filtered["date"], df_filtered[metric], marker="o")
                    ax2.set_title(f"{metric} の推移")
                    ax2.set_xlabel("日付")
                    ax2.set_ylabel(metric)
                    ax2.grid(True)
                    ax2 = format_xaxis_as_date(ax2, df_filtered)
                    st.pyplot(fig2)

        if st.button("グラフを表示"):
            metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
            for metric in metrics:
                fig, ax = plt.subplots(figsize=(10, 3))
                ax.plot(df_filtered["date"], df_filtered[metric], marker="o")
                ax.set_title(f"{selected_name} の {metric} の経時変化")
                ax.set_xlabel("記録日時")
                ax.set_ylabel(metric)
                ax.grid(True)
                ax = format_xaxis_as_date(ax, df_filtered)
                st.pyplot(fig)
    else:
        st.info("記録がまだありません。")
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

# ページ：患者管理
if page == "患者管理":
    st.title("患者管理リスト")
    df = pd.read_sql_query("SELECT * FROM shunt_records", conn)
    if not df.empty:
        name_counts = df.groupby("name")["id"].count().reset_index().rename(columns={"id": "記録数"})
        st.dataframe(name_counts)

        selected_name = st.selectbox("患者氏名を選択", name_counts["name"].unique())
        patient_data = df[df["name"] == selected_name].sort_values(by="date")
        st.write(f"### {selected_name} の記録一覧")
        st.dataframe(patient_data)

        if st.button("この患者のグラフを表示"):
            metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
            for metric in metrics:
                fig, ax = plt.subplots(figsize=(10, 3))
                ax.plot(patient_data["date"], patient_data[metric], marker="o")
                ax.set_title(f"{selected_name} の {metric} の経時変化")
                ax.set_xlabel("記録日時")
                ax.set_ylabel(metric)
                ax.grid(True)
                st.pyplot(fig)

        st.write("### 氏名の修正（氏名単位）")
        unique_names = df["name"].dropna().unique().tolist()
        edit_target_name = st.selectbox("修正対象の氏名", unique_names)
        new_name = st.text_input("新しい氏名", value=edit_target_name)
        if st.button("氏名を更新"):
            cursor = conn.cursor()
            cursor.execute("UPDATE shunt_records SET name = ? WHERE name = ?", (new_name, edit_target_name))
            conn.commit()
            st.success("氏名を更新しました。ページを再読み込みしてください。")

        st.write("### 記録の削除（氏名単位）")
        delete_target_name = st.selectbox("削除する氏名", unique_names, key="delete")
        if st.button("記録を削除"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM shunt_records WHERE name = ?", (delete_target_name,))
            conn.commit()
            st.success("記録を削除しました。ページを再読み込みしてください。")
    else:
        st.info("現在記録されている患者はいません。")

# ページ：患者データ一覧
if page == "患者データ一覧":
    st.title("患者データ一覧（ボタン形式 + 特記事項比較）")
    df = pd.read_sql_query("SELECT * FROM shunt_records", conn)
    if not df.empty:
        unique_names = df["name"].dropna().unique().tolist()
        for name in unique_names:
            if st.button(f"{name} の記録を見る"):
                patient_data = df[df["name"] == name].sort_values(by="date")
                st.write(f"### {name} の記録一覧")
                st.dataframe(patient_data)

                if st.button(f"{name} の統計を表示"):
                    st.subheader("📊 各項目の統計（平均・標準偏差）")
                    metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
                    stats_data = {
                        "項目": metrics,
                        "平均": [round(np.mean(patient_data[m]), 2) for m in metrics],
                        "標準偏差": [round(np.std(patient_data[m], ddof=1), 2) for m in metrics]
                    }
                    st.dataframe(pd.DataFrame(stats_data))

        st.markdown("---")
        st.subheader("📊 特記事項カテゴリでの比較")
        categories = ["術前評価", "術後評価", "定期評価", "VAIVT前評価", "VAIVT後評価"]
        selected_category = st.selectbox("特記事項を選択して記録を表示", categories, key="cat_view")
        cat_data = df[df["tag"] == selected_category]
        st.write(f"#### {selected_category} の記録一覧")
        st.dataframe(cat_data)

        compare_categories = st.multiselect("比較したいカテゴリを選択（2つまで）", categories)
        if len(compare_categories) == 2:
            compare_data = df[df["tag"].isin(compare_categories)]
            if st.button("有意差を検定"):
                st.markdown("#### ※Mann-Whitney U検定")
                metrics = ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]
                p_results = {"項目": [], "p値": []}

                for metric in metrics:
                    group1 = compare_data[compare_data["tag"] == compare_categories[0]][metric]
                    group2 = compare_data[compare_data["tag"] == compare_categories[1]][metric]
                    if len(group1) > 0 and len(group2) > 0:
                        stat, p = mannwhitneyu(group1, group2, alternative='two-sided')
                        p_results["項目"].append(metric)
                        p_results["p値"].append(round(p, 4))
                st.dataframe(pd.DataFrame(p_results))

            st.markdown("---")
            st.subheader("📈 箱ひげ図による比較")
            for metric in ["FV", "RI", "PI", "TAV", "TAMV", "PSV", "EDV"]:
                fig = draw_boxplot_with_median_outliers(compare_data, metric, "tag")
                st.pyplot(fig)
    else:
        st.info("患者データが存在しません。")

