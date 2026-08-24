"""日次入出庫実績シート(daily_transactions)生成。

SKUごとに独立乱数系列で需要パターン(src/demand_pattern.py)を生成したうえで、
補充ロジック(src/replenishment.py)により発注要否判定→入庫反映→出庫/欠品/在庫更新を
日付順に確定させる。本ファイルは両モジュールを束ねるオーケストレータに徹する。

在庫残は「入庫−実出庫の累積」でマイナスにならず、不足分は backorder_qty として
翌日以降に繰り越される(発注情報は持たない、観測実績のみのダミーデータ)。
"""

from datetime import date

import numpy as np
import pandas as pd

from src.common.calendar import business_day_position_lookup, generate_calendar
from src.common.config import SETTINGS, Settings
from src.demand_pattern import compute_demand
from src.product_master import generate_product_master
from src.replenishment import build_replenishment_params, simulate_replenishment


def _effective_start_idx(row: pd.Series, calendar_df: pd.DataFrame, settings: Settings) -> int:
    """SKUの補充ロジックが動き出す最初の行位置。新製品はローンチの14日前から
    在庫を持てるようにする(発売前の先行入荷を表現)。既存品は常にデータ開始日から。"""
    launch_date = pd.Timestamp(row["launch_date"])
    start_date = pd.Timestamp(settings.start_date)
    effective_start = max(start_date, launch_date - pd.Timedelta(days=14))

    idx = calendar_df.index[calendar_df["date"] >= effective_start]
    return int(idx[0]) if len(idx) else len(calendar_df)


def generate_daily_transactions(settings: Settings = SETTINGS) -> pd.DataFrame:
    product_master = generate_product_master(settings)
    calendar_df = generate_calendar(date.fromisoformat(settings.start_date), settings.num_years, settings)
    bidx_lookup = business_day_position_lookup(calendar_df)

    frames = []
    for offset, (_, row) in enumerate(product_master.iterrows()):
        seed = settings.random_seed + 200 + offset

        demand = compute_demand(row, calendar_df, settings, seed)
        params = build_replenishment_params(row, settings)
        effective_start_idx = _effective_start_idx(row, calendar_df, settings)
        rng = np.random.default_rng(seed + 1)
        result = simulate_replenishment(demand, calendar_df, effective_start_idx, params, bidx_lookup, rng)

        sku_df = pd.DataFrame({
            "date": calendar_df["date"],
            "sku_code": row["sku_code"],
            "category": row["category"],
            "status": row["status"],
            "inbound_qty": result["inbound_qty"],
            "demand_qty": demand,
            "shipped_qty": result["shipped_qty"],
            "backorder_qty": result["backorder_qty"],
            "stock_on_hand": result["stock_on_hand"],
            "order_qty": result["order_qty"],
        })
        frames.append(sku_df)

    return pd.concat(frames, ignore_index=True).sort_values(["date", "sku_code"]).reset_index(drop=True)
