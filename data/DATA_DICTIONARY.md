# データ辞書

すべて合成データ生成用のダミー値。実在の企業・商品・物量とは無関係。

## product_master

| 列名 | 型 | 内容 |
|---|---|---|
| sku_code | str | 商品コード(例: `NB-001`)。カテゴリ別接頭辞(NB=ノートPC/DT=デスクトップPC/MN=モニター) |
| category | str | ノートPC / デスクトップPC / モニター |
| status | str | 売れ筋 / 新製品 / 終売間近 |
| launch_date | date | 投入日。新製品はデータ期間内、既存品(売れ筋/終売間近)はデータ開始日以前 |
| ramp_speed | float | 新製品のみ。立ち上げカーブ(ロジスティック曲線)の傾き係数 |
| initial_level | float | 新製品のみ。立ち上げ初速(安定期需要に対する初日時点の比率) |
| stabilize_days | int | 新製品のみ。需要が安定化するまでの目安日数 |
| decay_rate | float | 終売間近のみ。1日あたりの需要減衰率(指数減衰) |
| lead_time_days | int | 発注〜入庫のリードタイム(営業日)。全SKU共通で乱数付与 |
| safety_stock_days | float | 安全在庫日数(営業日、トレーリング平均需要に対する係数)。全SKU共通で乱数付与 |
| review_interval_days | int | 定期発注方式の発注間隔(営業日)。発注点方式選択時は未使用だが常に全SKUへ格納 |

## daily_transactions

| 列名 | 型 | 内容 |
|---|---|---|
| date | date | 日付(2年分、日次) |
| sku_code | str | 商品コード |
| category | str | カテゴリ(product_masterから複製、Excel PY関数での集計の利便性のため) |
| status | str | ステータス(同上) |
| inbound_qty | int | 入庫数(実績)。過去に発注した`order_qty`がリードタイム経過後に着荷した日のみ非ゼロ |
| demand_qty | int | 出庫需要数(引当要求数)。その日新たに発生した需要のみで、繰越backorderは含まない |
| shipped_qty | int | 実出庫数。`demand_qty + 前日backorder_qty`と在庫のいずれか小さい方 |
| backorder_qty | int | バックオーダー残(繰越)。機会損失として消えず翌日に繰り越される |
| stock_on_hand | int | 在庫残。入庫−実出庫の累積で、マイナスにはならない |
| order_qty | int | 発注量。補充ロジック(定期発注方式/発注点方式)が発注した日のみ非ゼロ、`lead_time_days`後に`inbound_qty`として着荷する |

## weekly_forecast

| 列名 | 型 | 内容 |
|---|---|---|
| week_start | date | 週の開始日(月曜) |
| category | str | カテゴリ(SKU別ではなくカテゴリ単位) |
| forecast_qty | int | 荷主提供の週次forecast出庫数(カテゴリ合計)。actual_qtyにカテゴリ別ノイズを加えて生成 |
| actual_qty | int | 検証用。daily_transactionsのshipped_qtyをカテゴリ×週で集計した実績値 |
