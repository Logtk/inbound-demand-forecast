"""需要予測モデル用の特徴量を組み立てる。

予測対象は`demand_qty`(引当要求数)。仕様書の業務制約により3PL側は発注日・発注理由を
見られないため、`season_index`のような生成時の内部パラメータは特徴量へ含めず、
`month`とラグ特徴量からモデル自身に季節性を発見させる(Volume_forecast_portfolioの
`src/part1_inventory/features.py`と同じ設計方針)。

`demand_qty`は仕様書上「引当要求数」として3PL側が観測可能な値であり、`shipped_qty`と
異なり欠品によって打ち切られない。そのためVolume_forecast_portfolioのPart1のような
欠品履歴特徴量(stockout_lag_*)は不要で、このモジュールでは扱わない。
"""

import pandas as pd

GROUP_COLS = ["sku_code"]
LAG_DAYS = [7, 14, 21, 28]
LAG_COLUMNS = [f"lag_{n}" for n in LAG_DAYS]

CATEGORICAL_COLUMNS = ["sku_code", "category", "status"]
FEATURE_COLUMNS = [
    "dow", "month", "category", "status", "sku_code",
    *LAG_COLUMNS, "rolling_same_dow_mean",
]
TARGET_COLUMN = "demand_qty"


def add_lag_features(df: pd.DataFrame, group_cols: list, target_col: str, lag_days: list) -> pd.DataFrame:
    df = df.sort_values(group_cols + ["date"]).copy()
    grouped = df.groupby(group_cols)[target_col]
    for n in lag_days:
        df[f"lag_{n}"] = grouped.shift(n)
    return df


def add_rolling_same_dow_mean(
    df: pd.DataFrame, lag_cols: list, output_col: str = "rolling_same_dow_mean"
) -> pd.DataFrame:
    df = df.copy()
    df[output_col] = df[lag_cols].mean(axis=1)
    return df


def add_month_feature(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = pd.DatetimeIndex(df["date"]).month
    return df


def add_dow_feature(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dow"] = pd.DatetimeIndex(df["date"]).dayofweek
    return df


def build_feature_set(df: pd.DataFrame) -> pd.DataFrame:
    df = add_dow_feature(df)

    # ラグは暦日ベースの全日カレンダーに対して計算する(shift(7)が文字通り「1週間前の同曜日」に
    # なるようにするため)。土日を先に除いてから行位置でshiftすると1週間=5行になり
    # 曜日がズレるので、必ずフィルタ前に計算する。
    df = add_lag_features(df, GROUP_COLS, TARGET_COLUMN, LAG_DAYS)
    df = add_rolling_same_dow_mean(df, LAG_COLUMNS)
    df = add_month_feature(df)

    df = df[df["dow"] < 5].copy()  # 学習・評価対象は平日のみ(土日は需要0で稼働なし)
    df = df.dropna(subset=LAG_COLUMNS).reset_index(drop=True)
    return df
