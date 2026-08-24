"""需要パターン(季節性・新製品ランプ/終売減衰)を生成する。

補充ロジック(src/replenishment.py)からは完全に独立させる。需要生成の乱数シード系列
(random_seed+200+offset)は発注方式を切り替えても変化しないため、demand_qtyは
`replenishment_policy`に依存しない(tests/test_replenishment.py::
test_policy_switch_preserves_demand_realization で保証)。
"""

import numpy as np
import pandas as pd

from src.common.config import Settings


def status_factor(row: pd.Series, dates: pd.DatetimeIndex, settings: Settings) -> np.ndarray:
    launch_date = pd.Timestamp(row["launch_date"])
    status = row["status"]

    if status == "新製品":
        days_since_launch = (dates - launch_date).days.to_numpy(dtype=float)
        ramp_speed = float(row["ramp_speed"])
        initial_level = float(row["initial_level"])
        stabilize_days = float(row["stabilize_days"])
        logistic = initial_level + (1 - initial_level) / (
            1 + np.exp(-ramp_speed * (days_since_launch - stabilize_days / 2))
        )
        return np.where(days_since_launch < 0, 0.0, logistic)

    if status == "終売間近":
        start = pd.Timestamp(settings.start_date)
        days_since_start = (dates - start).days.to_numpy(dtype=float)
        decay_rate = float(row["decay_rate"])
        return np.exp(-decay_rate * np.clip(days_since_start, 0, None))

    return np.ones(len(dates))


def compute_demand(row: pd.Series, calendar_df: pd.DataFrame, settings: Settings, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dates = pd.DatetimeIndex(calendar_df["date"])

    dow_coef = calendar_df["dow"].map(settings.dow_coefficients).to_numpy(dtype=float)
    season = calendar_df["season_index"].to_numpy(dtype=float)
    factor = status_factor(row, dates, settings)
    base = settings.base_daily_demand_by_category[row["category"]] * settings.base_daily_demand_multiplier
    noise = rng.normal(1.0, settings.demand_noise_std, size=len(dates))

    demand = base * factor * dow_coef * season * noise
    return np.clip(np.round(demand), 0, None).astype(int)
