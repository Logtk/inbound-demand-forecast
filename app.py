"""入出庫ダミーデータ生成シミュレーター(Streamlit UI)。

補充ロジック(発注方式・リードタイム・安全在庫)と需要パターン(季節性・基準需要水準・
ノイズ)をUIから調整し、生成結果(欠品率・在庫推移)を確認できる。実データ・実企業は
一切使用しない。詳細は docs/design.md を参照。
"""

import dataclasses

import altair as alt
import streamlit as st

from src.common.config import SETTINGS, Settings
from src.export_excel import build_excel_bytes, build_workbook
from src.scenario_kpi import summarize_scenario

st.set_page_config(page_title="入出庫ダミーデータ生成シミュレーター", page_icon="📦", layout="wide")

st.title("📦 入出庫ダミーデータ生成シミュレーター")
st.caption("国内3PL事業者の入出庫実績パターンを想定した合成データ生成器。実データ・実企業は一切使用しません。")
st.markdown(
    "発注方式・需要パターンを変えて、終売間近SKUの欠品率がどう変わるかを確認できます。"
    "詳細は `docs/design.md` を参照してください。"
)

policy_label = st.radio(
    "発注方式", ["定期発注方式", "発注点方式"], horizontal=True,
    help="定期発注方式=一定間隔で発注。発注点方式=在庫ポジションが発注点を下回ったら都度発注。",
)
policy = "periodic" if policy_label == "定期発注方式" else "reorder_point"

with st.form("scenario_form"):
    col_foundation, col_action = st.columns(2)
    with col_foundation:
        st.markdown("**🌤️ 土台(需要パターン)** — 外部の需要環境")
        base_mult = st.slider("基準需要水準の倍率", 0.5, 2.0, 1.0, 0.1)
        season_mult = st.slider(
            "季節性の強さ", 0.0, 2.0, 1.0, 0.1,
            help="0=季節性フラット、1=既定、2=繁忙期をより強調",
        )
        noise_std = st.slider("需要のノイズ幅(標準偏差)", 0.0, 0.4, 0.15, 0.01)
    with col_action:
        st.markdown("**🛠️ 打ち手(補充ロジック)** — 倉庫運用側の設計変数")
        lead_time_range = st.slider("リードタイム(営業日)", 1, 30, (3, 10))
        safety_days_range = st.slider("安全在庫日数", 0, 20, (3, 10))
        trailing_window = st.slider("発注量算出に使う実績参照期間(営業日)", 7, 60, 28)
        if policy == "periodic":
            review_interval_range = st.slider("発注間隔(営業日)", 5, 30, (10, 20))
        else:
            review_interval_range = SETTINGS.periodic_review_interval_business_days_range
            st.caption("発注点方式は毎営業日、在庫ポジションと発注点を比較して発注要否を判定します。")

    submitted = st.form_submit_button("この設定で生成する", use_container_width=True)


@st.cache_data(show_spinner="ダミーデータを生成しています…")
def run_scenario(settings: Settings) -> dict:
    return build_workbook(settings)


if submitted:
    scenario_settings = dataclasses.replace(
        SETTINGS,
        replenishment_policy=policy,
        base_daily_demand_multiplier=base_mult,
        seasonal_amplitude_multiplier=season_mult,
        demand_noise_std=noise_std,
        lead_time_business_days_range=lead_time_range,
        safety_stock_days_range=safety_days_range,
        trailing_window_days=trailing_window,
        periodic_review_interval_business_days_range=review_interval_range,
    )
    st.session_state["scenario_settings"] = scenario_settings
    st.session_state["scenario_sheets"] = run_scenario(scenario_settings)

if "scenario_sheets" not in st.session_state:
    st.info("上のフォームから設定して「この設定で生成する」を押してください。")
    st.stop()

sheets = st.session_state["scenario_sheets"]
daily_df = sheets["daily_transactions"]

tab_kpi, tab_stock, tab_compare, tab_data = st.tabs(
    ["📊 KPIサマリー", "📈 在庫推移", "⚖️ 定期発注 vs 発注点 比較", "🗂 データ確認/エクスポート"]
)

with tab_kpi:
    summary = summarize_scenario(daily_df)
    st.metric("全体backorder発生率", f"{summary.overall_backorder_rate:.1%}")

    cols = st.columns(len(summary.by_status))
    for col, (_, row) in zip(cols, summary.by_status.iterrows()):
        col.metric(row["status"], f"{row['backorder_rate']:.1%}")

    st.markdown("**カテゴリ別backorder発生率**")
    st.dataframe(summary.by_category, use_container_width=True, hide_index=True)

    st.markdown("**status別 平均在庫日数(カバレッジ)**")
    st.dataframe(summary.coverage_days_by_status, use_container_width=True, hide_index=True)

    st.caption(
        "旧実装では終売間近SKUの発注ロジックが期間全体(未来を含む)の平均需要でロットサイズを"
        "決めていたため、backorder発生率が55〜70%まで悪化するバグがあった。トレーリング平均+"
        "在庫ポジションに作り替えたことで、ステータス間の差が現実的な水準に収まっている。"
    )

with tab_stock:
    sku_options = sorted(daily_df["sku_code"].unique())
    selected_sku = st.selectbox("SKUを選択", sku_options)
    sku_df = daily_df[daily_df["sku_code"] == selected_sku].sort_values("date")

    melted = sku_df.melt(
        id_vars="date", value_vars=["stock_on_hand", "backorder_qty", "inbound_qty"],
        var_name="指標", value_name="数量",
    )
    chart = alt.Chart(melted).mark_line().encode(
        x="date:T", y="数量:Q", color="指標:N"
    ).properties(height=400)
    st.altair_chart(chart, use_container_width=True)

with tab_compare:
    st.caption(
        "需要パターン・リードタイム・安全在庫は固定したまま、発注方式だけを両方実行して比較します"
        "(demand_qtyは両方式で完全に一致します)。"
    )
    base_settings = st.session_state["scenario_settings"]
    periodic_settings = dataclasses.replace(base_settings, replenishment_policy="periodic")
    reorder_settings = dataclasses.replace(base_settings, replenishment_policy="reorder_point")

    periodic_daily = run_scenario(periodic_settings)["daily_transactions"]
    reorder_daily = run_scenario(reorder_settings)["daily_transactions"]

    periodic_summary = summarize_scenario(periodic_daily)
    reorder_summary = summarize_scenario(reorder_daily)

    compare_df = periodic_summary.by_status.merge(
        reorder_summary.by_status, on="status", suffixes=("_定期発注方式", "_発注点方式")
    )
    st.dataframe(compare_df, use_container_width=True, hide_index=True)

with tab_data:
    for name, df in sheets.items():
        st.subheader(name)
        st.dataframe(df.head(20), use_container_width=True)

    excel_bytes = build_excel_bytes(sheets)
    st.download_button(
        "xlsxをダウンロード", data=excel_bytes, file_name="inbound_demand_dummy.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
