"""需要予測モデルの評価、および荷主週次forecastの精度検証。

このモジュールは2つの評価軸を独立に扱う:

1. **SKU日次モデル評価**: ベースライン(前週同曜日平均) vs LightGBMの`demand_qty`
   (引当要求数、欠品による打ち切りを受けない値)予測精度をWAPE/MAPEで比較する。
2. **週次forecast精度検証**: `weekly_forecast`シートの`forecast_qty`(荷主提供)を
   `actual_qty`(shipped_qtyの週次カテゴリ集計)と突き合わせてMAPEを算出する。
   仕様書が「精度検証は未実施」と明記する核心的な改善余地そのものに対応する。

(1)のモデルは`demand_qty`を、(2)の`actual_qty`は`shipped_qty`由来であり、両者は
欠品発生時に乖離する別概念のため、日次モデルの予測を週次に集計して`actual_qty`と
突き合わせる際は、この乖離が誤差に混入する点を明記する(3節)。
"""

import numpy as np
import pandas as pd

from src.features import TARGET_COLUMN


def compute_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]))


def compute_wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sum(np.abs(y_true - y_pred)) / np.sum(y_true))


def _metrics_row(group_label: str, df: pd.DataFrame, baseline_col: str, model_col: str) -> list:
    rows = []
    for method, col in [("baseline", baseline_col), ("lightgbm", model_col)]:
        rows.append({
            "group": group_label,
            "method": method,
            "mape": compute_mape(df[TARGET_COLUMN].to_numpy(), df[col].to_numpy()),
            "wape": compute_wape(df[TARGET_COLUMN].to_numpy(), df[col].to_numpy()),
            "n": len(df),
        })
    return rows


def compare_baseline_vs_model(test_df: pd.DataFrame, baseline_col: str, model_col: str) -> pd.DataFrame:
    """1. SKU日次モデル評価: 全体・カテゴリ別・ステータス別にWAPE/MAPEを比較する。"""
    rows = _metrics_row("全体", test_df, baseline_col, model_col)
    for category, group_df in test_df.groupby("category"):
        rows += _metrics_row(category, group_df, baseline_col, model_col)
    for status, group_df in test_df.groupby("status"):
        rows += _metrics_row(f"status={status}", group_df, baseline_col, model_col)
    return pd.DataFrame(rows)


def evaluate_shipper_forecast(weekly_forecast_df: pd.DataFrame) -> pd.DataFrame:
    """2. 週次forecast精度検証: モデルを介さず、荷主forecast_qty vs actual_qtyのみで算出する。"""
    rows = []
    for category, group_df in weekly_forecast_df.groupby("category"):
        rows.append({
            "category": category,
            "n_weeks": len(group_df),
            "mape": compute_mape(group_df["actual_qty"].to_numpy(), group_df["forecast_qty"].to_numpy()),
            "wape": compute_wape(group_df["actual_qty"].to_numpy(), group_df["forecast_qty"].to_numpy()),
        })
    overall = {
        "category": "全体",
        "n_weeks": len(weekly_forecast_df),
        "mape": compute_mape(
            weekly_forecast_df["actual_qty"].to_numpy(), weekly_forecast_df["forecast_qty"].to_numpy()
        ),
        "wape": compute_wape(
            weekly_forecast_df["actual_qty"].to_numpy(), weekly_forecast_df["forecast_qty"].to_numpy()
        ),
    }
    return pd.DataFrame([overall, *rows])


def build_weekly_model_forecast(test_df: pd.DataFrame, model_col: str) -> pd.DataFrame:
    """test期間の日次SKUモデル予測をカテゴリ×週(月曜始まり)に集計する。"""
    df = test_df.copy()
    dates = pd.to_datetime(df["date"])
    df["week_start"] = dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")
    return (
        df.groupby(["week_start", "category"])
        .agg(model_forecast_qty=(model_col, "sum"), demand_qty_actual=(TARGET_COLUMN, "sum"))
        .reset_index()
    )


def compare_shipper_vs_model_forecast(
    weekly_model_df: pd.DataFrame, weekly_forecast_df: pd.DataFrame
) -> pd.DataFrame:
    """3. 荷主forecast vs 3PL自前モデルを、同じactual_qty(shipped_qty週次集計)基準で比較する。

    モデルはdemand_qty(引当要求数)を予測しているため、backorderが発生した週は
    actual_qty(=shipped_qty)との間にdemand-shipped乖離が誤差として混入する。
    厳密な同一指標比較ではない点を前提として明記したうえでの参考値。
    """
    merged = weekly_model_df.merge(
        weekly_forecast_df[["week_start", "category", "forecast_qty", "actual_qty"]],
        on=["week_start", "category"],
    )

    rows = []
    for category, g in merged.groupby("category"):
        rows.append({
            "category": category,
            "n_weeks": len(g),
            "shipper_mape": compute_mape(g["actual_qty"].to_numpy(), g["forecast_qty"].to_numpy()),
            "model_mape": compute_mape(g["actual_qty"].to_numpy(), g["model_forecast_qty"].to_numpy()),
            "shipper_wape": compute_wape(g["actual_qty"].to_numpy(), g["forecast_qty"].to_numpy()),
            "model_wape": compute_wape(g["actual_qty"].to_numpy(), g["model_forecast_qty"].to_numpy()),
        })
    overall = {
        "category": "全体",
        "n_weeks": len(merged),
        "shipper_mape": compute_mape(merged["actual_qty"].to_numpy(), merged["forecast_qty"].to_numpy()),
        "model_mape": compute_mape(merged["actual_qty"].to_numpy(), merged["model_forecast_qty"].to_numpy()),
        "shipper_wape": compute_wape(merged["actual_qty"].to_numpy(), merged["forecast_qty"].to_numpy()),
        "model_wape": compute_wape(merged["actual_qty"].to_numpy(), merged["model_forecast_qty"].to_numpy()),
    }
    return pd.DataFrame([overall, *rows])
