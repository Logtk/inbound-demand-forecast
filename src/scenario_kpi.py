"""シナリオKPI集計。Streamlit非依存の純粋関数のみで構成し、UIなしでもテスト可能にする。"""

from dataclasses import dataclass

import pandas as pd


def backorder_rate_by_status(daily_df: pd.DataFrame) -> pd.DataFrame:
    result = daily_df.groupby("status")["backorder_qty"].apply(lambda s: (s > 0).mean()).reset_index()
    result.columns = ["status", "backorder_rate"]
    return result


def backorder_rate_by_category(daily_df: pd.DataFrame) -> pd.DataFrame:
    result = daily_df.groupby("category")["backorder_qty"].apply(lambda s: (s > 0).mean()).reset_index()
    result.columns = ["category", "backorder_rate"]
    return result


def avg_stock_coverage_days(daily_df: pd.DataFrame) -> pd.DataFrame:
    """status別に 平均stock_on_hand ÷ 平均shipped_qty(在庫日数換算)を集計する。"""
    grouped = daily_df.groupby("status").agg(
        avg_stock=("stock_on_hand", "mean"), avg_shipped=("shipped_qty", "mean")
    ).reset_index()
    grouped["coverage_days"] = grouped["avg_stock"] / grouped["avg_shipped"].replace(0, pd.NA)
    return grouped


@dataclass
class ScenarioSummary:
    overall_backorder_rate: float
    by_status: pd.DataFrame
    by_category: pd.DataFrame
    coverage_days_by_status: pd.DataFrame


def summarize_scenario(daily_df: pd.DataFrame) -> ScenarioSummary:
    return ScenarioSummary(
        overall_backorder_rate=float((daily_df["backorder_qty"] > 0).mean()),
        by_status=backorder_rate_by_status(daily_df),
        by_category=backorder_rate_by_category(daily_df),
        coverage_days_by_status=avg_stock_coverage_days(daily_df),
    )
