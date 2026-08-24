"""補充ロジック(発注方式)。

定期発注方式・発注点方式のどちらも「目標在庫水準(target level)まで発注する」という
同じ発注量算出式を共有し、違いは「いつ発注要否を判定するか」だけにする((s,S)型への統一)。

target_level = trailing_avg_demand(発注時点までの実績のみ) × coverage_days
  定期発注: coverage_days = 発注間隔 + リードタイム + 安全在庫日数(スケジュール到来で発注)
  発注点  : coverage_days = リードタイム + 安全在庫日数(在庫ポジション ≤ 発注点で毎営業日判定)
order_qty = max(0, target_level − inventory_position)
  inventory_position = 手持在庫 + 未入庫発注残 − backorder_qty

旧実装は「期間全体(2年分・未来を含む)の平均需要」でロットサイズを決めていたため、
終売間近SKU(需要が指数減衰する)で発注時点にはまだ起きていない未来の需要まで見て
発注量を決めるlook-aheadリークになっていた(期間前半のロットが恒常的に過小になり、
backorder発生率が55〜70%まで悪化する不具合の原因)。`compute_trailing_mean`が
発注日より前の実績のみを参照することでこれを構造的に解消する。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.common.config import Settings


@dataclass(frozen=True)
class ReplenishmentParams:
    """SKUごとに発注時点で3PLが知りうる値のみを保持する(生涯平均など未来情報は含まない)。"""

    policy: str  # "periodic" | "reorder_point"
    lead_time_days: int  # 発注〜入庫のリードタイム(営業日)
    safety_stock_days: float  # 安全在庫日数(営業日、trailing平均に対する係数)
    review_interval_days: int  # 定期発注方式の発注間隔(営業日)
    review_jitter_probability: float
    review_jitter_extra_days_range: tuple
    trailing_window_days: int
    trailing_min_periods_days: int
    order_qty_noise_std: float
    fallback_daily_demand: float  # トレーリング実績不足時に使うカテゴリ基準需要


def build_replenishment_params(row: pd.Series, settings: Settings) -> ReplenishmentParams:
    fallback = settings.base_daily_demand_by_category[row["category"]] * settings.base_daily_demand_multiplier
    return ReplenishmentParams(
        policy=settings.replenishment_policy,
        lead_time_days=int(row["lead_time_days"]),
        safety_stock_days=float(row["safety_stock_days"]),
        review_interval_days=int(row["review_interval_days"]),
        review_jitter_probability=settings.periodic_review_jitter_probability,
        review_jitter_extra_days_range=settings.periodic_review_jitter_extra_days_range,
        trailing_window_days=settings.trailing_window_days,
        trailing_min_periods_days=settings.trailing_min_periods_days,
        order_qty_noise_std=settings.order_qty_noise_std,
        fallback_daily_demand=fallback,
    )


def compute_trailing_mean(
    demand: np.ndarray,
    is_business_day: np.ndarray,
    window_days: int,
    min_periods_days: int,
    fallback_value: float,
) -> np.ndarray:
    """発注判断に使える「発注日より前」のトレーリング平均需要を営業日ベースで計算する。

    `demand`は暦日(土日=0)で生成されているため、暦日ウィンドウでそのまま平均すると
    土日のゼロが混入し実勢より過小になる(features.pyのラグ特徴量で暦日shiftが
    必要だったのと同じ種類の落とし穴)。営業日のみを抽出した系列に対して
    rolling(window_days営業日).mean().shift(1)を適用することで、(1)当日を含まない
    (look-ahead防止)、(2)土日のゼロで薄まらない、の両方を満たす。

    戻り値は`demand`と同じ長さの配列。非営業日の値は使われないため未定義でよい。
    """
    n = len(demand)
    biz_idx = np.where(is_business_day)[0]
    biz_demand = demand[biz_idx].astype(float)

    trailing_biz = (
        pd.Series(biz_demand).rolling(window=window_days, min_periods=min_periods_days).mean().shift(1)
    )
    trailing_biz = trailing_biz.fillna(fallback_value).to_numpy()

    result = np.full(n, fallback_value, dtype=float)
    result[biz_idx] = trailing_biz
    return result


def simulate_replenishment(
    demand: np.ndarray,
    calendar_df: pd.DataFrame,
    effective_start_idx: int,
    params: ReplenishmentParams,
    bidx_lookup: np.ndarray,
    rng: np.random.Generator,
) -> dict:
    """発注要否判定→入庫反映→出庫/欠品/在庫更新を日付順の単一ループで行う。

    発注点方式は当日の在庫状態を見て判定するため、両方式が同じ発注量算出式を使う以上、
    定期発注方式も含めて在庫ポジション依存の1ループにする(2フェーズ構成は取らない)。
    """
    n = len(demand)
    is_biz = calendar_df["is_business_day"].to_numpy()
    bidx = calendar_df["business_day_index"].to_numpy()
    max_bidx = int(bidx[-1])

    trailing_mean = compute_trailing_mean(
        demand, is_biz, params.trailing_window_days, params.trailing_min_periods_days,
        params.fallback_daily_demand,
    )

    inbound = np.zeros(n, dtype=int)
    shipped = np.zeros(n, dtype=int)
    backorder = np.zeros(n, dtype=int)
    stock_arr = np.zeros(n, dtype=int)
    order_qty_arr = np.zeros(n, dtype=int)

    stock = 0
    on_order = 0
    backorder_carry = 0
    pending: dict = {}  # 行位置(着荷日) -> 数量
    next_review_bidx = bidx[effective_start_idx] if params.policy == "periodic" else None

    for i in range(effective_start_idx, n):
        arrived = pending.pop(i, 0)
        if arrived:
            stock += arrived
            on_order -= arrived
        inbound[i] = arrived

        if is_biz[i]:
            inventory_position = stock + on_order - backorder_carry

            if params.policy == "periodic":
                coverage_days = params.review_interval_days + params.lead_time_days + params.safety_stock_days
                should_order = bidx[i] >= next_review_bidx
            else:  # reorder_point
                coverage_days = params.lead_time_days + params.safety_stock_days
                reorder_threshold = trailing_mean[i] * coverage_days
                should_order = inventory_position <= reorder_threshold

            if should_order:
                target_level = trailing_mean[i] * coverage_days
                raw_qty = max(0.0, target_level - inventory_position)
                if raw_qty > 0:
                    noise = max(rng.normal(1.0, params.order_qty_noise_std), 0.3)
                    order_qty = int(round(raw_qty * noise))
                    if order_qty > 0:
                        target_bidx = min(bidx[i] + params.lead_time_days, max_bidx)
                        arrival_pos = int(bidx_lookup[target_bidx])
                        pending[arrival_pos] = pending.get(arrival_pos, 0) + order_qty
                        on_order += order_qty
                        order_qty_arr[i] = order_qty

                if params.policy == "periodic":
                    interval = params.review_interval_days
                    if rng.random() < params.review_jitter_probability:
                        interval += int(rng.integers(*params.review_jitter_extra_days_range))
                    next_review_bidx = bidx[i] + interval

        required = int(demand[i]) + backorder_carry
        shipped_today = min(required, stock)
        stock -= shipped_today
        backorder_carry = required - shipped_today

        shipped[i] = shipped_today
        backorder[i] = backorder_carry
        stock_arr[i] = stock

    return {
        "inbound_qty": inbound,
        "shipped_qty": shipped,
        "backorder_qty": backorder,
        "stock_on_hand": stock_arr,
        "order_qty": order_qty_arr,
    }
