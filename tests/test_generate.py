"""ダミーデータ生成ロジックの不変条件を検証する。"""

import pandas as pd
import pytest

from src.common.config import SETTINGS
from src.daily_transactions import generate_daily_transactions
from src.product_master import generate_product_master
from src.weekly_forecast import generate_weekly_forecast


@pytest.fixture(scope="module")
def product_master_df():
    return generate_product_master(SETTINGS)


@pytest.fixture(scope="module")
def daily_df():
    return generate_daily_transactions(SETTINGS)


@pytest.fixture(scope="module")
def weekly_df(daily_df):
    return generate_weekly_forecast(daily_df, SETTINGS)


def test_product_master_has_30_skus(product_master_df):
    assert len(product_master_df) == 30
    assert product_master_df["sku_code"].is_unique


def test_product_master_status_distribution_matches_config(product_master_df):
    for category, counts in SETTINGS.status_distribution.items():
        cat_df = product_master_df[product_master_df["category"] == category]
        assert len(cat_df) == SETTINGS.skus_per_category
        for status, expected_count in counts.items():
            actual_count = (cat_df["status"] == status).sum()
            assert actual_count == expected_count, f"{category}/{status}"


def test_new_products_have_ramp_params_others_dont(product_master_df):
    new_products = product_master_df[product_master_df["status"] == "新製品"]
    others = product_master_df[product_master_df["status"] != "新製品"]

    assert new_products["ramp_speed"].notna().all()
    assert new_products["initial_level"].notna().all()
    assert new_products["stabilize_days"].notna().all()
    assert others["ramp_speed"].isna().all()


def test_daily_transactions_row_count(daily_df, product_master_df):
    expected_days = daily_df["date"].nunique()
    assert len(daily_df) == len(product_master_df) * expected_days
    # 2024年はうるう年のため2年間は730日ではなく731日になる
    assert expected_days == 731


def test_stock_on_hand_never_negative(daily_df):
    assert (daily_df["stock_on_hand"] >= 0).all()


def test_backorder_never_negative(daily_df):
    assert (daily_df["backorder_qty"] >= 0).all()


def test_shipped_never_exceeds_demand_plus_prior_backorder(daily_df):
    for sku, sku_df in daily_df.groupby("sku_code"):
        sku_df = sku_df.sort_values("date").reset_index(drop=True)
        prior_backorder = sku_df["backorder_qty"].shift(1).fillna(0).astype(int)
        required = sku_df["demand_qty"] + prior_backorder
        assert (sku_df["shipped_qty"] <= required).all(), sku


def test_stock_balance_identity_holds(daily_df):
    """stock_on_hand[t] == stock_on_hand[t-1] + inbound_qty[t] - shipped_qty[t] が全SKUで成立する。"""
    for sku, sku_df in daily_df.groupby("sku_code"):
        sku_df = sku_df.sort_values("date").reset_index(drop=True)
        prior_stock = sku_df["stock_on_hand"].shift(1).fillna(0).astype(int)
        expected = prior_stock + sku_df["inbound_qty"] - sku_df["shipped_qty"]
        assert (sku_df["stock_on_hand"] == expected).all(), sku


def test_backorder_identity_holds(daily_df):
    """backorder_qty[t] == demand_qty[t] + backorder_qty[t-1] - shipped_qty[t] が全SKUで成立する。"""
    for sku, sku_df in daily_df.groupby("sku_code"):
        sku_df = sku_df.sort_values("date").reset_index(drop=True)
        prior_backorder = sku_df["backorder_qty"].shift(1).fillna(0).astype(int)
        expected = sku_df["demand_qty"] + prior_backorder - sku_df["shipped_qty"]
        assert (sku_df["backorder_qty"] == expected).all(), sku


def test_weekly_forecast_actual_matches_daily_aggregation(daily_df, weekly_df):
    df = daily_df.copy()
    dates = pd.to_datetime(df["date"])
    df["week_start"] = dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")
    recomputed = (
        df.groupby(["week_start", "category"])["shipped_qty"].sum().reset_index()
    )

    merged = weekly_df.merge(
        recomputed, on=["week_start", "category"], suffixes=("", "_recomputed")
    )
    assert len(merged) == len(weekly_df)
    assert (merged["actual_qty"] == merged["shipped_qty"]).all()


def test_weekly_forecast_noise_within_configured_bounds(weekly_df):
    for category, pct in SETTINGS.forecast_noise_pct_by_category.items():
        cat_df = weekly_df[(weekly_df["category"] == category) & (weekly_df["actual_qty"] > 0)]
        diff_ratio = (cat_df["forecast_qty"] - cat_df["actual_qty"]).abs() / cat_df["actual_qty"]
        assert (diff_ratio <= pct + 1e-6).all()
