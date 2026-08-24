"""需要予測モデル 実行スクリプト。

1. SKU日次のdemand_qtyについて、ベースライン(前週同曜日平均)とLightGBMを
   時系列検証(2024年学習/2025年検証)で比較する。
2. weekly_forecastシートの荷主forecast_qtyをactual_qtyと突き合わせ、
   精度検証が未実施だった週次forecastのMAPE/WAPEを算出する。
3. 日次モデル予測をカテゴリ×週に集計し、荷主forecastとの精度比較を行う
   (demand_qty予測とactual_qty=shipped_qty集計の概念差は評価前提として明記)。

本評価は手法・特徴量設計の実証であり、実データでの精度を保証するものではない。
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.baseline import compute_baseline_forecast
from src.common.config import SETTINGS
from src.daily_transactions import generate_daily_transactions
from src.evaluate import (
    compare_baseline_vs_model,
    compare_shipper_vs_model_forecast,
    build_weekly_model_forecast,
    evaluate_shipper_forecast,
)
from src.features import TARGET_COLUMN, build_feature_set
from src.model import predict_demand, split_train_test, train_lightgbm_model
from src.weekly_forecast import generate_weekly_forecast

plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE_DIR / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

BASELINE_COL = "baseline_pred"
MODEL_COL = "model_pred"


def plot_baseline_vs_model_metrics(metrics_df: pd.DataFrame, output_path: Path) -> None:
    overall = metrics_df[metrics_df["group"] == "全体"]
    baseline_wape = overall.loc[overall["method"] == "baseline", "wape"].iloc[0]
    model_wape = overall.loc[overall["method"] == "lightgbm", "wape"].iloc[0]
    improvement = (baseline_wape - model_wape) / baseline_wape

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    bars = ax.bar(
        ["前週同曜日平均\n(現場の勘)", "AI予測\n(LightGBM)"],
        [baseline_wape, model_wape],
        color=["#8a97a0", "#1f6f63"],
        width=0.55,
    )
    for bar, value in zip(bars, [baseline_wape, model_wape]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.006, f"{value:.1%}",
                 ha="center", fontsize=12, fontweight="bold")

    ax.annotate(
        f"誤差 {improvement:.0%} 削減",
        xy=(1, model_wape), xytext=(0.5, baseline_wape * 0.9),
        ha="center", fontsize=12, color="#1f6f63", fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": "#1f6f63"},
    )
    ax.set_title("SKU日次需要予測の誤差比較(合成データによる検証)", fontsize=11)
    ax.set_ylabel("誤差率(WAPE・低いほど良い)")
    ax.set_ylim(0, baseline_wape * 1.25)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)


def plot_forecast_overlay(test_df: pd.DataFrame, output_path: Path, sample_month: str = "2025-03") -> None:
    df = test_df[pd.to_datetime(test_df["date"]).dt.strftime("%Y-%m") == sample_month]
    daily = df.groupby("date").agg(
        actual=(TARGET_COLUMN, "sum"), baseline=(BASELINE_COL, "sum"), model=(MODEL_COL, "sum"),
    )

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(daily.index, daily["actual"], color="#333333", linewidth=2, label="実績(demand_qty)")
    ax.plot(daily.index, daily["baseline"], color="#8a97a0", linestyle="--", linewidth=1.5,
             label="前週同曜日平均")
    ax.plot(daily.index, daily["model"], color="#1f6f63", linewidth=1.8, label="AI予測(LightGBM)")

    ax.set_title(f"日次需要の予測と実績(全SKU合計・{sample_month}・合成データ)", fontsize=11)
    ax.set_ylabel("需要数量(個/日)")
    ax.legend(fontsize=9)
    fig.autofmt_xdate()

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)


def plot_shipper_vs_model_wape(comparison_df: pd.DataFrame, output_path: Path) -> None:
    plot_df = comparison_df[comparison_df["category"] != "全体"].set_index("category")[
        ["shipper_wape", "model_wape"]
    ]

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    plot_df.plot(kind="bar", ax=ax, color=["#c96f2f", "#1f6f63"], rot=0)
    for container in ax.containers:
        labels = [f"{v:.1%}" for v in container.datavalues]
        ax.bar_label(container, labels=labels, fontsize=9, padding=2)
    ax.set_title("週次forecast精度: 荷主提供 vs 3PL自前モデル(合成データ)", fontsize=11)
    ax.set_ylabel("誤差率(WAPE・低いほど良い)")
    ax.set_xlabel("")
    ax.legend(["荷主forecast", "3PL自前モデル(demand_qty集計)"], fontsize=9)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)


def main() -> None:
    daily_df = generate_daily_transactions(SETTINGS)
    weekly_forecast_df = generate_weekly_forecast(daily_df, SETTINGS)

    feature_df = build_feature_set(daily_df)
    train_df, test_df = split_train_test(feature_df)

    test_df = test_df.copy()
    test_df[BASELINE_COL] = compute_baseline_forecast(test_df)

    model = train_lightgbm_model(train_df, SETTINGS)
    test_df[MODEL_COL] = predict_demand(model, test_df)

    print("=== 1. SKU日次需要予測: ベースライン vs LightGBM(時系列検証: 2025年) ===")
    metrics_df = compare_baseline_vs_model(test_df, BASELINE_COL, MODEL_COL)
    print(metrics_df.to_string(index=False))
    print(
        "  [注記] status=終売間近ではLightGBMがベースラインより悪化する(木ベースモデルは"
        "学習期間の値域を外れた継続的な減衰トレンドを外挿できないため。検証期間の実測値は"
        "学習期間より大きく低い水準まで減衰しており、モデルの限界を示す結果として明記する)。"
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_df.to_csv(REPORTS_DIR / "forecast_metrics.csv", index=False, encoding="utf-8-sig")

    print("\n=== 2. 週次forecast精度検証(荷主forecast_qty vs actual_qty、モデル不使用) ===")
    shipper_accuracy_df = evaluate_shipper_forecast(weekly_forecast_df)
    print(shipper_accuracy_df.to_string(index=False))
    shipper_accuracy_df.to_csv(REPORTS_DIR / "weekly_shipper_forecast_accuracy.csv", index=False, encoding="utf-8-sig")

    print("\n=== 3. 荷主forecast vs 3PL自前モデル(参考値、demand-shipped概念差あり) ===")
    weekly_model_df = build_weekly_model_forecast(test_df, MODEL_COL)
    comparison_df = compare_shipper_vs_model_forecast(weekly_model_df, weekly_forecast_df)
    print(comparison_df.to_string(index=False))
    print(
        "  [注記] 全体ではモデルがわずかに上回るが、カテゴリ別では一様ではない"
        "(例: ノートPCは荷主forecastの方が精度が高い場合がある)。3PL自前モデルが"
        "荷主forecastを常に上回るわけではなく、両者を併用したクロスチェックとして"
        "位置づけるのが妥当。"
    )
    comparison_df.to_csv(REPORTS_DIR / "weekly_shipper_vs_model.csv", index=False, encoding="utf-8-sig")

    plot_baseline_vs_model_metrics(metrics_df, FIGURES_DIR / "forecast_baseline_vs_model_wape.png")
    plot_forecast_overlay(test_df, FIGURES_DIR / "forecast_overlay.png")
    plot_shipper_vs_model_wape(comparison_df, FIGURES_DIR / "weekly_shipper_vs_model_wape.png")

    overall_baseline_wape = metrics_df.query("group=='全体' and method=='baseline'")["wape"].iloc[0]
    overall_model_wape = metrics_df.query("group=='全体' and method=='lightgbm'")["wape"].iloc[0]
    passed = overall_model_wape < overall_baseline_wape
    print(
        f"\n=== 合格判定: LightGBM WAPE({overall_model_wape:.4f}) < "
        f"ベースライン WAPE({overall_baseline_wape:.4f}) => {'PASS' if passed else 'FAIL'} ==="
    )


if __name__ == "__main__":
    main()
