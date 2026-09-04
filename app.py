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

st.set_page_config(page_title="倉庫の発注ルール最適化シミュレーター", page_icon="📦", layout="wide")

st.title("📦 倉庫の発注ルール最適化シミュレーター")
st.markdown(
    "このツールは、「**発注のルール(安全在庫など)を変えたときに、欠品がどれくらい減り、"
    "倉庫の在庫がどれくらい増えるか**」をあらかじめテストするための画面です。"
)
with st.expander("技術的な補足(合成データ・再現性について)"):
    st.caption(
        "国内3PL事業者の入出庫実績パターンを想定した合成データ生成器です。実データ・実企業は"
        "一切使用しません。詳細は `docs/design.md` を参照してください。"
    )

st.subheader("1. 条件を設定する")

policy_label = st.radio(
    "発注方式", ["定期発注方式", "発注点方式"], horizontal=True,
    help="定期発注方式=一定間隔で発注。発注点方式=在庫ポジションが発注点を下回ったら都度発注。",
)
policy = "periodic" if policy_label == "定期発注方式" else "reorder_point"

with st.form("scenario_form"):
    col_foundation, col_action = st.columns(2)
    with col_foundation:
        st.markdown("**① 荷主の動き**")
        st.caption("出荷量のブレや繁忙期の波を設定します(基本はそのままでOKです)。")
        base_mult = st.slider(
            "基準需要水準の倍率", 0.5, 2.0, 1.0, 0.1,
            help="1.0が標準的な出荷量です。荷主の取扱量が普段より多い/少ない想定にしたいときに動かしてください。",
        )
        season_mult = st.slider(
            "季節性の強さ", 0.0, 2.0, 1.0, 0.1,
            help="0=繁忙期・閑散期の差が無い、1=標準的な波、2=繁忙期の山をより急にする。",
        )
        noise_std = st.slider(
            "需要のノイズ幅(標準偏差)", 0.0, 0.4, 0.15, 0.01,
            help="日々の出荷量のランダムなブレの大きさです。大きいほど予測しづらい荷動きになります。",
        )
    with col_action:
        st.markdown("**② 倉庫のルール**")
        st.caption("「安全在庫」や「発注ペース」を調整してみてください。")
        lead_time_range = st.slider(
            "リードタイム(営業日)", 1, 30, (3, 10),
            help="発注してから商品が倉庫に届くまでの日数です。長いほど早めに発注しないと欠品しやすくなります。",
        )
        safety_days_range = st.slider(
            "安全在庫日数", 0, 20, (3, 10),
            help="需要のブレに備えて余分に持っておく在庫の日数です。増やすと欠品は減りますが、在庫(倉庫スペース)は増えます。",
        )
        trailing_window = st.slider(
            "発注量算出に使う実績参照期間(営業日)", 7, 60, 28,
            help="直近何日分の出荷実績を見て、次の発注量を決めるかです。",
        )
        if policy == "periodic":
            review_interval_range = st.slider(
                "発注間隔(営業日)", 5, 30, (10, 20),
                help="何営業日おきに発注するかです。短いほどこまめに発注でき、在庫を少なく保ちやすくなります。",
            )
        else:
            review_interval_range = SETTINGS.periodic_review_interval_business_days_range
            st.caption("発注点方式は毎営業日、在庫ポジションと発注点を比較して発注要否を判定します。")

    submitted = st.form_submit_button("▶ この設定でシミュレーションを実行", use_container_width=True)


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
    st.info("上のフォームから設定して「▶ この設定でシミュレーションを実行」を押してください。")
    st.stop()

sheets = st.session_state["scenario_sheets"]
daily_df = sheets["daily_transactions"]
active_settings = st.session_state["scenario_settings"]

tab_kpi, tab_stock, tab_compare, tab_data = st.tabs(
    ["📊 結果を確認する", "📈 在庫推移", "⚖️ 定期発注 vs 発注点 比較", "🗂 データ確認/エクスポート"]
)

with tab_kpi:
    st.markdown("### 2. 結果を確認する — チェックすべき2つのポイント")
    summary = summarize_scenario(daily_df)

    st.markdown("**① 「欠品(出荷不能)」は防げているか？**")
    st.metric("出荷不能率(注文に対して出荷できなかった日の割合)", f"{summary.overall_backorder_rate:.1%}")
    st.caption(
        "値は低いほど良好です。参考: 過去にこのロジックを作り込む過程で、設定を誤ると"
        "55〜70%まで悪化する実装バグが実際にありました(現在は修正済み)。それに比べれば"
        "一桁台〜10%程度のこの水準は現実的な範囲です。安全在庫日数を増やすと下がる傾向にあります"
        "(ただし②の在庫は増えます)。"
    )
    cols = st.columns(len(summary.by_status))
    for col, (_, row) in zip(cols, summary.by_status.iterrows()):
        col.metric(row["status"], f"{row['backorder_rate']:.1%}")

    st.markdown("**カテゴリ別 出荷不能率**")
    st.dataframe(summary.by_category, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("**② 「在庫の山」になっていないか？**")
    safety_lo, safety_hi = active_settings.safety_stock_days_range
    st.caption(
        f"今回設定した安全在庫日数の目安は **{safety_lo}〜{safety_hi}日** です。下表の「抱えている"
        "在庫日数」がこれより大幅に多い場合、狙い以上に在庫を持ちすぎている(倉庫スペースを圧迫している)"
        "可能性があります。"
    )
    coverage_view = summary.coverage_days_by_status.rename(columns={"coverage_days": "抱えている在庫日数"})
    st.dataframe(coverage_view, use_container_width=True, hide_index=True)

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
