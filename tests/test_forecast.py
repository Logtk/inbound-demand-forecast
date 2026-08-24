"""需要予測モデル(features/baseline/model/evaluate)の回帰テスト。実APIは使用しない。"""

import numpy as np
import pandas as pd
import pytest

from src.baseline import compute_baseline_forecast
from src.common.config import SETTINGS
from src.daily_transactions import generate_daily_transactions
from src.evaluate import (
    compare_baseline_vs_model,
    compare_shipper_vs_model_forecast,
    build_weekly_model_forecast,
    compute_mape,
    compute_wape,
    evaluate_shipper_forecast,
)
from src.features import LAG_DAYS, TARGET_COLUMN, build_feature_set
from src.model import predict_demand, split_train_test, train_lightgbm_model
from src.weekly_forecast import generate_weekly_forecast


@pytest.fixture(scope="module")
def daily_df():
    return generate_daily_transactions(SETTINGS)


@pytest.fixture(scope="module")
def feature_df(daily_df):
    return build_feature_set(daily_df)


@pytest.fixture(scope="module")
def trained_test_df(feature_df):
    train_df, test_df = split_train_test(feature_df)
    test_df = test_df.copy()
    test_df["baseline_pred"] = compute_baseline_forecast(test_df)
    model = train_lightgbm_model(train_df, SETTINGS)
    test_df["model_pred"] = predict_demand(model, test_df)
    return test_df


def test_compute_mape_and_wape_known_values():
    y_true = np.array([100.0, 200.0, 0.0])
    y_pred = np.array([110.0, 180.0, 5.0])
    # mapeは実測0の行を除外する
    assert compute_mape(y_true, y_pred) == pytest.approx((0.1 + 0.1) / 2)
    assert compute_wape(y_true, y_pred) == pytest.approx((10 + 20 + 5) / 300)


def test_feature_set_only_weekdays(feature_df):
    assert (pd.DatetimeIndex(feature_df["date"]).dayofweek < 5).all()


def test_lag7_matches_same_weekday_previous_week(daily_df, feature_df):
    """lag_7が「7暦日前=前週同曜日」の値と一致することを検証する(business-day基準の
    行位置shiftだと曜日がずれるため、暦日ベースで計算していることの確認)。"""
    sample = feature_df.iloc[len(feature_df) // 2]
    sku = sample["sku_code"]
    target_date = pd.Timestamp(sample["date"])
    prior_date = target_date - pd.Timedelta(days=7)

    sku_daily = daily_df[daily_df["sku_code"] == sku].set_index("date")
    expected = sku_daily.loc[pd.Timestamp(prior_date), TARGET_COLUMN]
    assert sample["lag_7"] == expected


def test_no_lag_columns_have_nan(feature_df):
    lag_cols = [f"lag_{n}" for n in LAG_DAYS]
    assert not feature_df[lag_cols].isna().any().any()


def test_baseline_forecast_uses_rolling_column(feature_df):
    baseline = compute_baseline_forecast(feature_df)
    assert (baseline == feature_df["rolling_same_dow_mean"]).all()


def test_model_predicts_nonnegative_reasonable_values(trained_test_df):
    preds = trained_test_df["model_pred"]
    assert len(preds) > 0
    assert preds.notna().all()
    # 需要数量として非現実的な値(極端な負や桁違いの値)になっていないことを大まかに確認
    assert (preds > -10).all()
    assert preds.max() < trained_test_df[TARGET_COLUMN].max() * 5


def test_lightgbm_beats_baseline_overall_wape(trained_test_df):
    metrics_df = compare_baseline_vs_model(trained_test_df, "baseline_pred", "model_pred")
    overall = metrics_df[metrics_df["group"] == "全体"]
    baseline_wape = overall.loc[overall["method"] == "baseline", "wape"].iloc[0]
    model_wape = overall.loc[overall["method"] == "lightgbm", "wape"].iloc[0]
    assert model_wape < baseline_wape


def test_evaluate_shipper_forecast_has_overall_and_category_rows(daily_df):
    weekly_forecast_df = generate_weekly_forecast(daily_df, SETTINGS)
    result = evaluate_shipper_forecast(weekly_forecast_df)
    assert "全体" in result["category"].to_list()
    for category in SETTINGS.categories:
        assert category in result["category"].to_list()
    assert (result["mape"] >= 0).all()
    assert (result["wape"] >= 0).all()


def test_compare_shipper_vs_model_forecast_aligns_weeks(daily_df, trained_test_df):
    weekly_forecast_df = generate_weekly_forecast(daily_df, SETTINGS)
    weekly_model_df = build_weekly_model_forecast(trained_test_df, "model_pred")
    comparison_df = compare_shipper_vs_model_forecast(weekly_model_df, weekly_forecast_df)

    assert "全体" in comparison_df["category"].to_list()
    assert comparison_df["n_weeks"].min() > 0
    for col in ["shipper_mape", "model_mape", "shipper_wape", "model_wape"]:
        assert (comparison_df[col] >= 0).all()
