"""週次forecastシート(weekly_forecast)生成。

daily_transactionsのshipped_qtyをカテゴリ×週(月曜始まり)で集計したactual_qtyに対し、
カテゴリ別の固定ノイズ幅を加えてforecast_qtyを生成する。後続のMAPE等の精度検証を
見据え、forecast_qtyとactual_qtyを両方保持する。
"""

import numpy as np
import pandas as pd

from src.common.config import SETTINGS, Settings
from src.daily_transactions import generate_daily_transactions


def generate_weekly_forecast(
    daily_df: pd.DataFrame = None, settings: Settings = SETTINGS
) -> pd.DataFrame:
    if daily_df is None:
        daily_df = generate_daily_transactions(settings)

    df = daily_df.copy()
    dates = pd.to_datetime(df["date"])
    df["week_start"] = dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")

    actual = (
        df.groupby(["week_start", "category"])["shipped_qty"]
        .sum()
        .reset_index()
        .rename(columns={"shipped_qty": "actual_qty"})
    )

    rng = np.random.default_rng(settings.random_seed + 900)
    noise_pct = actual["category"].map(settings.forecast_noise_pct_by_category).to_numpy(dtype=float)
    noise = rng.uniform(-1.0, 1.0, size=len(actual)) * noise_pct
    forecast_qty = np.clip(np.round(actual["actual_qty"] * (1 + noise)), 0, None).astype(int)
    actual["forecast_qty"] = forecast_qty

    return actual[["week_start", "category", "forecast_qty", "actual_qty"]].sort_values(
        ["week_start", "category"]
    ).reset_index(drop=True)
