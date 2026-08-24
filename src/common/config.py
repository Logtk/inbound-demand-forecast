"""パラメータをすべてダミー値として集約するモジュール。

すべて合成データ生成用のダミー値であり、実在の物量・商品・拠点とは無関係。
コード中に係数を直書きせず、必ずこのモジュール経由で参照すること。

仕様書「5. 未確定・要検討事項」に対応する仮値は、各フィールドのコメントに
根拠・調整可能であることを明記する。

需要パターン(base_daily_demand_multiplier/seasonal_amplitude_multiplier)と
補充ロジック(replenishment_policy以下)は、Streamlit UI(app.py)から
`dataclasses.replace(SETTINGS, ...)`で上書きして使う「土台/打ち手」変数。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    random_seed: int
    start_date: str
    num_years: int

    categories: tuple
    skus_per_category: int
    # カテゴリごとのステータス内訳(売れ筋/新製品/終売間近)。各カテゴリ合計10。
    status_distribution: dict

    # 売れ筋SKU1点あたりの平均日次需要(個/日)。カテゴリごとの規模感の仮値。
    base_daily_demand_by_category: dict
    # 基準需要水準の一律スケール(UI「土台」スライダー)。1.0=既定値。
    base_daily_demand_multiplier: float
    demand_noise_std: float

    # 月次季節係数レンジ。年度末3月・秋口9月の年2山を仮置き(未確定・要検討事項1)。
    # 実際のピーク月が判明次第、この辞書だけ差し替えれば良い設計。
    seasonal_index_by_month: dict
    # 季節係数の1.0からの乖離幅を拡大/縮小する倍率(UI「土台」スライダー)。
    # 0.0=季節性フラット、1.0=既定値、2.0=繁忙期をより強調。
    seasonal_amplitude_multiplier: float

    # 曜日係数(0=月〜6=日)。倉庫は土日稼働なしと仮定し0.0。
    dow_coefficients: dict

    # 新製品立ち上げカーブ(ロジスティック曲線)のSKUごとランダムパラメータ範囲
    ramp_speed_range: tuple
    initial_level_range: tuple
    stabilize_days_range: tuple

    # 終売間近SKUの日次減衰率レンジ(1日あたりの減衰割合)
    decay_rate_range: tuple

    # --- 補充ロジック(UI「打ち手」スライダー) ---
    # "periodic"(定期発注方式) | "reorder_point"(発注点方式)
    replenishment_policy: str
    # 発注量算出に使う実績トレーリング平均の参照期間(営業日数)
    trailing_window_days: int
    # トレーリング平均に必要な最低実績日数(未達時はカテゴリ基準需要で代替)
    trailing_min_periods_days: int
    # 発注〜入庫までのリードタイム(営業日、SKUごとに乱数でproduct_masterへ格納)
    lead_time_business_days_range: tuple
    # 安全在庫日数(SKUごとに乱数でproduct_masterへ格納)
    safety_stock_days_range: tuple
    # 定期発注方式の発注間隔(営業日、SKUごとに乱数でproduct_masterへ格納)
    periodic_review_interval_business_days_range: tuple
    # 定期発注方式: 一定確率で次回発注間隔が伸びる「ゆらぎ」
    periodic_review_jitter_probability: float
    periodic_review_jitter_extra_days_range: tuple
    # 発注量への乗算ノイズ(標準偏差)
    order_qty_noise_std: float

    # 週次forecastのカテゴリ別ノイズ幅(未確定・要検討事項3)。
    # ノートPC±10%・モニター±25%は仕様書の例をそのまま採用、デスクトップPCは仮に±15%。
    forecast_noise_pct_by_category: dict


SETTINGS = Settings(
    random_seed=42,
    start_date="2024-01-01",
    num_years=2,

    categories=("ノートPC", "デスクトップPC", "モニター"),
    skus_per_category=10,
    status_distribution={
        "ノートPC": {"売れ筋": 6, "新製品": 3, "終売間近": 1},
        "デスクトップPC": {"売れ筋": 5, "新製品": 3, "終売間近": 2},
        "モニター": {"売れ筋": 6, "新製品": 2, "終売間近": 2},
    },

    base_daily_demand_by_category={
        "ノートPC": 40.0,
        "デスクトップPC": 25.0,
        "モニター": 30.0,
    },
    base_daily_demand_multiplier=1.0,
    demand_noise_std=0.15,

    seasonal_index_by_month={
        1: (0.95, 1.05),
        2: (0.95, 1.05),
        3: (1.4, 1.8),
        4: (1.0, 1.1),
        5: (0.85, 0.95),
        6: (0.85, 0.95),
        7: (0.9, 1.0),
        8: (0.9, 1.0),
        9: (1.2, 1.4),
        10: (1.0, 1.1),
        11: (0.95, 1.05),
        12: (1.05, 1.2),
    },
    seasonal_amplitude_multiplier=1.0,

    dow_coefficients={
        0: 0.90,
        1: 1.05,
        2: 1.00,
        3: 1.00,
        4: 1.05,
        5: 0.0,
        6: 0.0,
    },

    ramp_speed_range=(0.05, 0.15),
    initial_level_range=(0.05, 0.2),
    stabilize_days_range=(30, 90),

    decay_rate_range=(0.0015, 0.005),

    replenishment_policy="periodic",
    trailing_window_days=28,
    trailing_min_periods_days=7,
    lead_time_business_days_range=(3, 10),
    safety_stock_days_range=(3, 10),
    periodic_review_interval_business_days_range=(10, 20),
    periodic_review_jitter_probability=0.2,
    periodic_review_jitter_extra_days_range=(5, 15),
    order_qty_noise_std=0.1,

    forecast_noise_pct_by_category={
        "ノートPC": 0.10,
        "デスクトップPC": 0.15,
        "モニター": 0.25,
    },
)
