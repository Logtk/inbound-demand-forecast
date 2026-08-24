"""商品マスタ(product_master)生成。

3カテゴリ×10SKU=30SKUを構成し、新製品には立ち上げカーブ(ロジスティック曲線)の
乱数パラメータを、終売間近品には減衰率を割り当てる。すべて匿名・合成のダミーデータ。

lead_time_days/safety_stock_days/review_interval_daysは全SKU共通で付与する
補充ロジック(src/replenishment.py)向けパラメータ。SKUごとに発注方式の挙動が
変わる現実的な状況(リードタイム・安全在庫のばらつき)を表現する。
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.common.config import SETTINGS, Settings

CATEGORY_PREFIX = {"ノートPC": "NB", "デスクトップPC": "DT", "モニター": "MN"}


def _build_sku_rows(settings: Settings) -> list:
    rows = []
    for category in settings.categories:
        status_counts = settings.status_distribution[category]
        statuses = []
        for status, count in status_counts.items():
            statuses.extend([status] * count)
        prefix = CATEGORY_PREFIX[category]
        for i, status in enumerate(statuses, start=1):
            rows.append({
                "sku_code": f"{prefix}-{i:03d}",
                "category": category,
                "status": status,
            })
    return rows


def generate_product_master(settings: Settings = SETTINGS) -> pd.DataFrame:
    df = pd.DataFrame(_build_sku_rows(settings))

    rng = np.random.default_rng(settings.random_seed + 100)
    start = date.fromisoformat(settings.start_date)
    total_days = settings.num_years * 365

    launch_dates, ramp_speed, initial_level, stabilize_days, decay_rate = [], [], [], [], []
    lead_time_days, safety_stock_days, review_interval_days = [], [], []

    for status in df["status"]:
        if status == "新製品":
            # データ期間前半(0〜全期間の70%)のどこかで投入し、立ち上げ推移を観測可能にする
            offset = int(rng.integers(0, int(total_days * 0.7)))
            launch_dates.append(start + timedelta(days=offset))
            ramp_speed.append(round(float(rng.uniform(*settings.ramp_speed_range)), 4))
            initial_level.append(round(float(rng.uniform(*settings.initial_level_range)), 4))
            stabilize_days.append(int(rng.integers(*settings.stabilize_days_range)))
            decay_rate.append(np.nan)
        else:
            # 既存品(売れ筋/終売間近): データ開始日以前(1〜5年前)に投入済みという扱い
            tenure_days = int(rng.integers(365, 1825))
            launch_dates.append(start - timedelta(days=tenure_days))
            ramp_speed.append(np.nan)
            initial_level.append(np.nan)
            stabilize_days.append(np.nan)
            if status == "終売間近":
                decay_rate.append(round(float(rng.uniform(*settings.decay_rate_range)), 6))
            else:
                decay_rate.append(np.nan)

        # 補充ロジック用パラメータ(全ステータス共通、src/replenishment.pyが参照)
        lead_time_days.append(int(rng.integers(*settings.lead_time_business_days_range)))
        safety_stock_days.append(round(float(rng.uniform(*settings.safety_stock_days_range)), 2))
        review_interval_days.append(
            int(rng.integers(*settings.periodic_review_interval_business_days_range))
        )

    df["launch_date"] = launch_dates
    df["ramp_speed"] = ramp_speed
    df["initial_level"] = initial_level
    df["stabilize_days"] = stabilize_days
    df["decay_rate"] = decay_rate
    df["lead_time_days"] = lead_time_days
    df["safety_stock_days"] = safety_stock_days
    df["review_interval_days"] = review_interval_days

    return df
