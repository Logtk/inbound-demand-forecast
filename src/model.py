"""LightGBMによる日次demand_qty予測。

学習/検証は時系列分割のみ(ランダム分割は使わない)。データ期間が2024-01-01〜2025-12-31
(Volume_forecast_portfolio Part1と同じ期間設計)のため、分割日も揃えて2025-01-01とする。
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from src.common.config import SETTINGS, Settings
from src.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMN

DEFAULT_SPLIT_DATE = "2025-01-01"


def split_train_test(df: pd.DataFrame, split_date: str = DEFAULT_SPLIT_DATE) -> tuple:
    train_df = df[df["date"] < split_date].reset_index(drop=True)
    test_df = df[df["date"] >= split_date].reset_index(drop=True)
    return train_df, test_df


def prepare_model_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in CATEGORICAL_COLUMNS:
        df[col] = df[col].astype("category")
    return df


def train_lightgbm_model(train_df: pd.DataFrame, settings: Settings = SETTINGS) -> LGBMRegressor:
    train_df = prepare_model_frame(train_df)
    model = LGBMRegressor(random_state=settings.random_seed, verbosity=-1)
    model.fit(
        train_df[FEATURE_COLUMNS],
        train_df[TARGET_COLUMN],
        categorical_feature=CATEGORICAL_COLUMNS,
    )
    return model


def predict_demand(model: LGBMRegressor, df: pd.DataFrame) -> np.ndarray:
    df = prepare_model_frame(df)
    return model.predict(df[FEATURE_COLUMNS])
