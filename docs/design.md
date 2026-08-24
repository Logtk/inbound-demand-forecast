# 設計書: 入庫実績パターンからの需給予測ダミーデータ

## 1. 背景・目的

国内3PL事業者における入出庫データから需給予測モデルを構築するための試作。
実データではなくダミーデータで検証し、最終的にExcel Python(PY関数)で読み込んで分析する想定。

本プロジェクトは合成データによるポートフォリオ作品であり、実在の企業・商品・物量とは一切無関係。
すべての数値・SKU名・カテゴリ構成は匿名の仮想データとして生成する。

## 2. 業務制約(この設計の前提)

- 発注は荷主(顧客)の生産管理部門が行っており、3PL側からは発注日・発注理由が見えない。
- 3PL側で観測できるのは「入庫実績」「出庫実績(引当要求数・実出庫数)」のみ。
- → モデルは発注ロジックの推定ではなく、**入庫実績パターンからの需給予測**というアプローチを取る。
- 荷主から週次forecastが提供されるが、精度検証は未実施(これが本プロジェクトが可視化しようとしている
  核心的な改善余地。`weekly_forecast`シートに`forecast_qty`と`actual_qty`を両方保持するのはこの検証を
  後続フェーズで可能にするため)。

## 3. 出力形式

- Excel(.xlsx)、3シート構成(`product_master` / `daily_transactions` / `weekly_forecast`)
- Excel Python(PY関数)での読み込みを前提とする
- `python -m src.export_excel` で `data/synthetic/inbound_demand_dummy.xlsx` を生成(全量、gitignore対象)
- `data/synthetic/inbound_demand_dummy_sample.xlsx` は先頭14日分・全SKUのみを含む小片サンプルで、
  Git管理下に残す(`Volume_forecast_portfolio`と同じ運用)。

## 4. シート仕様

### 4.1 product_master(30行)

3カテゴリ(ノートPC/デスクトップPC/モニター)×各10SKU。
カテゴリごとのステータス内訳(`src/common/config.py`の`status_distribution`):

| カテゴリ | 売れ筋 | 新製品 | 終売間近 |
|---|---|---|---|
| ノートPC | 6 | 3 | 1 |
| デスクトップPC | 5 | 3 | 2 |
| モニター | 6 | 2 | 2 |

新製品には立ち上げカーブ(ロジスティック曲線)のパラメータ(`ramp_speed`/`initial_level`/
`stabilize_days`)を、終売間近品には日次減衰率(`decay_rate`)をSKUごとに乱数で割り当て、
仕様書の列一覧(`sku_code`/`category`/`status`/`launch_date`)に加えて列として保持する
(生成ロジックをExcel側からも追跡できるようにするための意図的な拡張)。第3フェーズ(8章)で
全SKU共通の補充ロジック用パラメータ(`lead_time_days`/`safety_stock_days`/`review_interval_days`)
も追加した。

### 4.2 daily_transactions(2年分×30SKU ≈ 21,930行)

列: `date`, `sku_code`, `category`, `status`, `inbound_qty`, `demand_qty`, `shipped_qty`,
`backorder_qty`, `stock_on_hand`, `order_qty`(発注日・発注量、8章の補充ロジックが追加)。

生成ロジックの要点(8章の汎用化で全面的に作り直した最終版):

- **需要**(`src/demand_pattern.py`): 季節性(月次係数)×曜日係数(土日は稼働なし=0と仮定)×
  ランダムノイズ。新製品はロジスティック立ち上げカーブ、終売間近は指数減衰トレンドを乗じる。
  補充ロジックとは乱数シード系列が完全に独立しており、発注方式を切り替えても`demand_qty`は
  一切変化しない。
- **補充(入庫・発注)**(`src/replenishment.py`): 定期発注方式・発注点方式のどちらも
  「目標在庫水準まで発注する」という同じ発注量算出式を共有する((s,S)型、8章参照)。
- **出庫・欠品・在庫**: SKUごとに日付順の逐次シミュレーション(`simulate_replenishment`)で
  以下の恒等式を厳密に満たすように計算する(`tests/test_generate.py`で全SKU・全日について検証済み)。
  - `stock_on_hand[t] = stock_on_hand[t-1] + inbound_qty[t] - shipped_qty[t]`(非負)
  - `backorder_qty[t] = demand_qty[t] + backorder_qty[t-1] - shipped_qty[t]`(非負、繰越)
  - `shipped_qty[t] = min(demand_qty[t] + backorder_qty[t-1], stock_on_hand[t-1] + inbound_qty[t])`

### 4.3 weekly_forecast(週×3カテゴリ ≈ 315行)

列: `week_start`(月曜始まり), `category`, `forecast_qty`, `actual_qty`。

`actual_qty`は`daily_transactions`の`shipped_qty`をカテゴリ×週で集計した値。`forecast_qty`は
`actual_qty`にカテゴリ別ノイズ幅を加えて生成する(荷主提供forecastの再現)。

## 5. 未確定・要検討事項への対応(仕様書5章)

仕様書で「実装時に相談・調整可能」とされた項目は、すべて`src/common/config.py`の`Settings`
dataclassに仮値として集約し、コード直書きを避けた。実際の値が判明した場合はこのファイルの
該当フィールドを差し替えるだけで再生成できる。

| 項目 | 仮値 | 根拠・備考 |
|---|---|---|
| 繁忙期の月 | 3月(1.4〜1.8倍)・9月(1.2〜1.4倍)の年2山 | 仕様書の例示(年度末3月・9月)をそのまま採用 |
| 定期発注の発注間隔(通常) | 10〜20営業日 | まとめて大量入庫のロジスティクス感覚での仮置き(8章で`periodic_review_interval_business_days_range`に改称) |
| 発注ゆらぎ発生確率 | 20% | 「一定確率で間隔が伸びる」を仮に2割と設定(`periodic_review_jitter_probability`) |
| 発注ゆらぎの追加日数 | 5〜15営業日 | 遅延相当を表現する仮値(`periodic_review_jitter_extra_days_range`) |
| forecastノイズ幅(ノートPC) | ±10% | 仕様書の例をそのまま採用 |
| forecastノイズ幅(モニター) | ±25% | 仕様書の例をそのまま採用 |
| forecastノイズ幅(デスクトップPC) | ±15% | 仕様書に例示なし、ノートPCとモニターの中間で仮置き |

8章の汎用化に伴い旧`inbound_lot_coverage_days_range`(入庫ロットが何日分の需要をカバーするか)は
廃止し、目標在庫水準の算出式(発注間隔+リードタイム+安全在庫日数)に統合した。

## 6. 需要予測モデル・週次forecast精度検証(第2フェーズ)

`Volume_forecast_portfolio`のPart1(ベースライン→LightGBM、時系列分割、WAPE評価)と同じ方法論を
踏襲し、`src/features.py`/`src/baseline.py`/`src/model.py`/`src/evaluate.py`/`src/run_forecast.py`
で実装した(`python -m src.run_forecast`で実行)。評価軸は独立した3つに分ける。

### 6.1 SKU日次需要予測(ベースライン vs LightGBM)

予測対象は`demand_qty`(引当要求数)。仕様書の業務制約上3PLは荷主の発注ロジックを見られないため、
`season_index`のような生成時内部パラメータは特徴量に含めず、`month`とラグ特徴量(7/14/21/28日)
からモデル自身に季節性を発見させる。ラグは**暦日ベース**で計算してから土日を除外する
(先に土日を除いてから行位置でshiftすると1週間が5行になり曜日がずれるため。実装時に発見し
`src/features.py`のコメントに明記)。時系列分割は2024年学習/2025年検証。

全体ではLightGBMがベースラインを上回る(WAPE 18.6%→15.6%、誤差16%削減)。ただし
**status別に見ると一様ではなく、終売間近SKUではLightGBMがベースラインより悪化する
(WAPE 21.0%→74.7%)**。原因は検証期間(2025年)の実測値が学習期間(2024年)より大きく
低い水準まで減衰しており、木ベースモデルは学習時に見た値域を外れた継続的な減衰トレンドを
外挿できないため(検証済み: 学習期間の`demand_qty`平均16.2・最小2に対し、検証期間は平均3.8・
最小1)。`decay_rate`を特徴量に加えれば改善しうるが、それは生成時の内部パラメータをモデルに
リークさせることになり6章冒頭の設計方針に反するため、あえて追加せず**木ベースモデルの限界を
示す結果として明記する**。

### 6.2 週次forecast精度検証(モデル不使用)

`weekly_forecast`の`forecast_qty`(荷主提供)を`actual_qty`(shipped_qty週次集計)と直接突き合わせ、
MAPE/WAPEを算出する(全体WAPE 7.9%、カテゴリ別ではノートPC4.8%〜モニター12.5%とばらつきがある)。
仕様書が「精度検証は未実施」と明記していた核心的な改善余地に、モデル構築を待たずそのまま応える。

### 6.3 荷主forecast vs 3PL自前モデル(参考比較)

6.1のSKU日次モデル予測をカテゴリ×週に集計し、6.2と同じ`actual_qty`基準で荷主forecastと比較する。
ただしモデルは`demand_qty`を、`actual_qty`は`shipped_qty`由来であり、欠品発生週はこの概念差が
誤差に混入する参考値である点を明記する。全体では3PL自前モデルがわずかに上回る(WAPE 7.6%→7.1%)が、
**カテゴリ別では一様ではなく、ノートPCは荷主forecastの方が精度が高い(4.9%<7.5%)**。3PL自前モデルが
常に荷主forecastを上回るわけではなく、両者を併用したクロスチェックとして位置づけるのが妥当という
結論を正直に記載する。

### 6.4 出力

`reports/forecast_metrics.csv`・`reports/weekly_shipper_forecast_accuracy.csv`・
`reports/weekly_shipper_vs_model.csv`・`reports/figures/*.png`(3枚: SKU日次WAPE比較・
2025年3月の日次予測実績オーバーレイ・週次forecast精度カテゴリ別比較)。

## 7. 第2フェーズ完了時点でのスコープ外事項

人時・コスト換算(本プロジェクトは労務費等のコストコンテキストを持たないため)、
GitHub Public公開作業。

## 8. 補充ロジック・需要パターンの汎用化 + Streamlit UI(第3フェーズ)

### 8.1 発端: look-aheadリークによるバグの発見

第2フェーズ完了後のレビューで、`daily_transactions`のstatus別backorder発生率が
売れ筋0.5%・新製品0%・**終売間近55〜70%**という現実離れした偏りを持つことが判明した。
原因は旧`_compute_inbound`が入庫ロットサイズを**期間全体(2年分・未来を含む)の平均需要**
(`demand[demand>0].mean()`)で決めていたこと。終売間近SKUは需要が指数減衰するため、
発注時点ではまだ起きていない未来の(低い)需要まで均して見てしまい、期間前半のロットが
恒常的に過小になっていた。

### 8.2 対応方針: 単発のバグ修正ではなく補充ロジック自体を汎用化

「現実の倉庫運用には様々な変数があり、それらに応用が効くフォーマットにしたい」という
方針のもと、バグ修正を補充ロジックの再設計に統合した。発注方式を**(s,S)型に統一**する。

```
target_level = trailing_avg_demand(発注時点までの実績のみ) × coverage_days
  定期発注方式: coverage_days = 発注間隔 + リードタイム + 安全在庫日数(スケジュール到来で発注)
  発注点方式  : coverage_days = リードタイム + 安全在庫日数(在庫ポジション ≤ 発注点で毎営業日判定)
order_qty = max(0, target_level − inventory_position)
  inventory_position = 手持在庫 + 未入庫発注残 − backorder_qty
```

`src/replenishment.py`の`compute_trailing_mean`が発注日**より前**の実績のみを参照することで
look-aheadを構造的に解消する。`demand`は日次(土日=0)で生成されているため、trailing平均を
単純に暦日ウィンドウで計算すると土日のゼロが混入し実勢より過小になる
(`src/features.py`のラグ特徴量で暦日shiftが必要だったのと同じ種類の落とし穴)。営業日のみを
抽出した系列に対して`rolling(window_days営業日).mean().shift(1)`を適用することで解消した。

### 8.3 結果: 修正後のbackorder発生率

| status | 修正前 | 修正後 |
|---|---|---|
| 売れ筋 | 0.5% | 8.1% |
| 新製品 | 0.0% | 10.0% |
| 終売間近 | 55〜70% | 4.0% |
| 全体 | — | 7.9% |

`tests/test_replenishment.py::test_discontinued_sku_backorder_rate_is_realistic`で
終売間近のbackorder発生率が20%未満であることを回帰的に保証する。

### 8.4 モジュール構成

- `src/common/config.py` — 需要パターン倍率(`base_daily_demand_multiplier`,
  `seasonal_amplitude_multiplier`)と補充ロジック(`replenishment_policy`,
  `trailing_window_days`, `lead_time_business_days_range`, `safety_stock_days_range`ほか)を追加。
- `src/product_master.py` — 全SKU共通で`lead_time_days`/`safety_stock_days`/`review_interval_days`
  を乱数追加。
- `src/common/calendar.py` — 季節振幅倍率の適用、`business_day_position_lookup`
  (リードタイム着荷日・次回発注タイミングの算出用)。
- `src/demand_pattern.py`(新規) — 需要パターン生成ロジックを`daily_transactions.py`から分離。
- `src/replenishment.py`(新規、中心モジュール) — `compute_trailing_mean`・
  `simulate_replenishment`(発注要否判定→入庫反映→出庫/欠品/在庫更新を単一ループで実施)。
- `src/daily_transactions.py` — 上記2モジュールを束ねるオーケストレータに縮小。
- `src/scenario_kpi.py`(新規) — Streamlit非依存のKPI集計純関数群。
- `app.py`(新規) — Streamlit UI。土台(需要パターン)/打ち手(補充ロジック)をフォームで入力し
  (`Freight_cost_simulator`の土台/打ち手分離パターンを踏襲)、生成ボタン確定時のみ
  `@st.cache_data`でキャッシュされた生成処理を実行する
  (`Sales_quote_optim`の「入力→計算→session_state保持→表示」パターンを踏襲)。
  KPIサマリー/在庫推移/定期発注vs発注点比較/データ確認・エクスポートの4タブ構成。

### 8.5 スコープ外(第3フェーズ時点)

在庫コスト制約(保管容量上限・在庫保有コスト等)、複数拠点・複数サプライヤー等のサプライチェーン
構造、安全在庫の統計的算出(サービスレベル%→z値→σ×√LT方式。今回は「日数×トレーリング平均」の
簡易方式を採用、σ推定が不安定になりやすいため見送った)。実データ対応への転換は対象外
(あくまでポートフォリオ内で完結する汎用化)。
