"""日次カレンダー・季節指数を生成する。Volume_forecast_portfolioの
src/common/calendar.pyの日付レンジ・季節指数パターンを本案件向けに移植。
"""

from datetime import date

import numpy as np
import pandas as pd

from src.common.config import Settings


def build_date_range(start_date: date, num_years: int) -> pd.DatetimeIndex:
    end_date = pd.Timestamp(start_date) + pd.DateOffset(years=num_years) - pd.Timedelta(days=1)
    return pd.date_range(start=start_date, end=end_date, freq="D")


def assign_dow(dates: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(dates.dayofweek, index=dates, name="dow")


def is_business_day(dates: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(dates.dayofweek < 5, index=dates, name="is_business_day")


def business_day_index(dates: pd.DatetimeIndex) -> pd.Series:
    """各日付までに経過した営業日の累積本数(その日が営業日ならその日を含む)。"""
    biz = is_business_day(dates)
    return pd.Series(biz.cumsum().to_numpy(), index=dates, name="business_day_index")


def compute_seasonal_index(dates: pd.DatetimeIndex, settings: Settings, seed: int) -> pd.Series:
    """月ごとに1つ乱数係数を引き、その月の全日に適用する(Volume_forecast_portfolioと同方式)。

    `seasonal_amplitude_multiplier`で1.0からの乖離幅を拡大/縮小する
    (0.0=季節性フラット、1.0=既定、2.0=繁忙期をより強調)。乱数の抽選順序・
    レンジ自体は変えず、季節性の「強弱」だけをUIから調整できるようにする。
    """
    rng = np.random.default_rng(seed)
    year_month = pd.PeriodIndex(dates.to_period("M"))
    month_coef = {}
    for ym in year_month.unique():
        lo, hi = settings.seasonal_index_by_month[ym.month]
        raw = rng.uniform(lo, hi)
        month_coef[ym] = 1.0 + (raw - 1.0) * settings.seasonal_amplitude_multiplier

    return pd.Series(
        [month_coef[ym] for ym in year_month], index=dates, name="season_index"
    )


def business_day_position_lookup(calendar_df: pd.DataFrame) -> np.ndarray:
    """business_day_index(1始まり)→ 行位置(0始まり)のルックアップ配列を返す。

    配列長は最大business_day_index+1(index 0は未使用)。src/replenishment.pyの
    リードタイム着荷日・定期発注の次回発注タイミング算出(「Nビジネス日後」を
    実際の行位置へ変換する)に使う。全SKUで共有できるよう1回だけ計算する。
    範囲外(データ期間末尾を超える)を指定した場合は最終営業日の行位置にクリップする。
    """
    max_bidx = int(calendar_df["business_day_index"].max())
    lookup = np.zeros(max_bidx + 1, dtype=int)
    biz_rows = calendar_df[calendar_df["is_business_day"]]
    lookup[biz_rows["business_day_index"].to_numpy()] = biz_rows.index.to_numpy()
    return lookup


def clip_business_day_index(bidx: int, calendar_df: pd.DataFrame) -> int:
    max_bidx = int(calendar_df["business_day_index"].max())
    return min(bidx, max_bidx)


def generate_calendar(start_date: date, num_years: int, settings: Settings) -> pd.DataFrame:
    dates = build_date_range(start_date, num_years)

    calendar_df = pd.DataFrame(index=dates)
    calendar_df["date"] = dates
    calendar_df["dow"] = assign_dow(dates).to_numpy()
    calendar_df["is_business_day"] = is_business_day(dates).to_numpy()
    calendar_df["business_day_index"] = business_day_index(dates).to_numpy()
    calendar_df["season_index"] = compute_seasonal_index(dates, settings, settings.random_seed).to_numpy()

    return calendar_df.reset_index(drop=True)
