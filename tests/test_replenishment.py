"""補充ロジック(src/replenishment.py)の回帰テスト。look-ahead解消の直接検証を中心に据える。"""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from src.common.config import SETTINGS
from src.daily_transactions import generate_daily_transactions
from src.replenishment import (
    ReplenishmentParams,
    compute_trailing_mean,
    simulate_replenishment,
)


def _make_all_business_calendar(n: int) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "date": dates,
        "is_business_day": [True] * n,
        "business_day_index": list(range(1, n + 1)),
    })


def _make_bidx_lookup(n: int) -> np.ndarray:
    lookup = np.zeros(n + 1, dtype=int)
    lookup[1 : n + 1] = np.arange(n)
    return lookup


def _base_params(**overrides) -> ReplenishmentParams:
    defaults = dict(
        policy="periodic",
        lead_time_days=5,
        safety_stock_days=2,
        review_interval_days=10,
        review_jitter_probability=0.0,
        review_jitter_extra_days_range=(1, 2),
        trailing_window_days=5,
        trailing_min_periods_days=1,
        order_qty_noise_std=0.0,
        fallback_daily_demand=20.0,
    )
    defaults.update(overrides)
    return ReplenishmentParams(**defaults)


def test_trailing_mean_unaffected_by_future_demand():
    is_biz = np.array([True] * 10)
    demand_a = np.array([10, 10, 10, 10, 10, 5, 5, 5, 5, 5], dtype=float)
    demand_b = np.array([10, 10, 10, 10, 10, 999, 999, 999, 999, 999], dtype=float)

    trailing_a = compute_trailing_mean(demand_a, is_biz, window_days=3, min_periods_days=1, fallback_value=0.0)
    trailing_b = compute_trailing_mean(demand_b, is_biz, window_days=3, min_periods_days=1, fallback_value=0.0)

    np.testing.assert_array_equal(trailing_a[:5], trailing_b[:5])


def test_order_qty_at_time_t_independent_of_future_demand():
    n = 60
    calendar_df = _make_all_business_calendar(n)
    bidx_lookup = _make_bidx_lookup(n)

    demand_a = np.array([20.0] * 50 + [5.0] * 10)
    demand_b = np.array([20.0] * 50 + [999.0] * 10)
    params = _base_params()

    result_a = simulate_replenishment(demand_a, calendar_df, 0, params, bidx_lookup, np.random.default_rng(1))
    result_b = simulate_replenishment(demand_b, calendar_df, 0, params, bidx_lookup, np.random.default_rng(1))

    np.testing.assert_array_equal(result_a["order_qty"][:40], result_b["order_qty"][:40])


def test_periodic_policy_orders_on_schedule():
    n = 40
    calendar_df = _make_all_business_calendar(n)
    bidx_lookup = _make_bidx_lookup(n)
    demand = np.array([10.0] * n)
    params = _base_params(policy="periodic", review_interval_days=10, lead_time_days=1, fallback_daily_demand=10.0)

    result = simulate_replenishment(demand, calendar_df, 0, params, bidx_lookup, np.random.default_rng(1))
    order_days = np.where(result["order_qty"] > 0)[0]

    # 発注間隔10日ごとに発注される(初回はeffective_start=0で即発注)
    assert order_days[0] == 0
    assert order_days[1] == 10
    assert order_days[2] == 20


def test_reorder_point_policy_triggers_below_reorder_point():
    n = 40
    calendar_df = _make_all_business_calendar(n)
    bidx_lookup = _make_bidx_lookup(n)
    demand = np.array([10.0] * n)
    params = _base_params(policy="reorder_point", lead_time_days=3, safety_stock_days=2)

    result = simulate_replenishment(demand, calendar_df, 0, params, bidx_lookup, np.random.default_rng(1))

    # 発注点方式は在庫が減るたびに繰り返し発注が発生する(定期発注のような固定間隔にはならない)
    assert (result["order_qty"] > 0).sum() >= 2
    # 常に在庫が枯渇し続けるわけではない(発注が効いて在庫が補充される)
    assert result["stock_on_hand"].max() > 0


def test_lead_time_delays_arrival():
    n = 30
    calendar_df = _make_all_business_calendar(n)
    bidx_lookup = _make_bidx_lookup(n)
    demand = np.array([10.0] * n)
    params = _base_params(policy="periodic", review_interval_days=100, lead_time_days=5)

    result = simulate_replenishment(demand, calendar_df, 0, params, bidx_lookup, np.random.default_rng(1))

    assert result["order_qty"][0] > 0
    assert result["inbound_qty"][:5].sum() == 0
    assert result["inbound_qty"][5] == result["order_qty"][0]


def test_discontinued_sku_backorder_rate_is_realistic():
    """旧実装で判明した終売間近SKUのbackorder発生率55〜70%というバグが解消されていることを確認する。"""
    daily_df = generate_daily_transactions(SETTINGS)
    by_status = daily_df.groupby("status")["backorder_qty"].apply(lambda s: (s > 0).mean())
    assert by_status["終売間近"] < 0.20


def test_base_demand_multiplier_scales_mean_demand():
    scaled_settings = dataclasses.replace(SETTINGS, base_daily_demand_multiplier=2.0)
    base_df = generate_daily_transactions(SETTINGS)
    scaled_df = generate_daily_transactions(scaled_settings)

    ratio = scaled_df["demand_qty"].mean() / base_df["demand_qty"].mean()
    assert 1.7 < ratio < 2.3


def test_policy_switch_preserves_demand_realization():
    periodic_settings = dataclasses.replace(SETTINGS, replenishment_policy="periodic")
    reorder_settings = dataclasses.replace(SETTINGS, replenishment_policy="reorder_point")

    periodic_df = generate_daily_transactions(periodic_settings)
    reorder_df = generate_daily_transactions(reorder_settings)

    pd.testing.assert_series_equal(
        periodic_df.sort_values(["sku_code", "date"])["demand_qty"].reset_index(drop=True),
        reorder_df.sort_values(["sku_code", "date"])["demand_qty"].reset_index(drop=True),
    )
