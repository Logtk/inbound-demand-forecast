"""ベースライン予測(前週同曜日平均=現場の勘の数値化)。

`features.py`が計算済みの`rolling_same_dow_mean`をそのまま予測値として使う薄いラッパー。
"""

import pandas as pd


def compute_baseline_forecast(df: pd.DataFrame, baseline_col: str = "rolling_same_dow_mean") -> pd.Series:
    return df[baseline_col]
