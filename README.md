# Inbound_demand_forecast_portfolio

国内3PL事業者の入出庫実績パターンから需給予測を試作するポートフォリオプロジェクト。
実データは一切使用せず、合成データ生成器・予測モデル一式を成果物とする匿名設計(GitHub公開前提)。

3PL側からは荷主の発注日・発注理由が見えないという業務制約を踏まえ、「発注ロジックの推定」ではなく
「入庫実績パターンからの需給予測」というアプローチを取る点が設計の核心。詳細は
[docs/design.md](docs/design.md) を参照。

## 1. ダミーデータ生成

`python -m src.export_excel` を実行すると、`data/synthetic/inbound_demand_dummy.xlsx` に
3シート(`product_master` / `daily_transactions` / `weekly_forecast`)を書き出す。
各列の意味は [data/DATA_DICTIONARY.md](data/DATA_DICTIONARY.md) を参照。

## 2. 需要予測モデル・週次forecast精度検証

`python -m src.run_forecast` を実行すると、以下の3つを評価する。

1. **SKU日次需要予測**: ベースライン(前週同曜日平均)とLightGBMを時系列検証(2024年学習/2025年
   検証)で比較(全体WAPE 18.6%→15.6%)。ただし終売間近SKUではLightGBMが悪化する
   (木ベースモデルが継続的な減衰トレンドを外挿できないため)。
2. **週次forecast精度検証**: `weekly_forecast`シートの荷主提供`forecast_qty`を`actual_qty`と
   突き合わせ、精度検証が未実施だった核心的な改善余地にモデル不使用でそのまま応える。
3. **荷主forecast vs 3PL自前モデル**: 全体では3PL自前モデルがわずかに上回るが、カテゴリ別では
   一様ではない(ノートPCは荷主forecastの方が精度が高い)。

結果は`reports/*.csv`・`reports/figures/*.png`に出力される。数値の解釈・非自明な結果の詳細は
[docs/design.md](docs/design.md) 6章を参照。

## 3. 補充ロジック・需要パターンのシミュレーター(Streamlit UI)

```bash
streamlit run app.py
```

発注方式(定期発注方式/発注点方式)・リードタイム・安全在庫などの補充ロジックと、季節性・
基準需要水準などの需要パターンをフォームから調整し、生成結果(欠品率・在庫推移)を確認できる。
旧実装では終売間近SKUの発注ロジックが期間全体(未来を含む)の平均需要でロットサイズを決めていた
ため、backorder発生率が55〜70%まで悪化するバグがあった。発注時点までの実績トレーリング平均+
在庫ポジションに作り替えたことでバグが解消された経緯は[docs/design.md](docs/design.md) 8章を参照。

## セットアップ

```bash
pip install -r requirements.txt
python -m src.export_excel
python -m src.run_forecast
streamlit run app.py
```

## テスト

```bash
python -m pytest tests/ -v
```

ダミーデータ生成の不変条件(在庫残・バックオーダー繰越の恒等式等)、補充ロジックのlook-ahead解消
(発注量が未来のdemand値に依存しないこと等)、予測モデルの回帰テスト(LightGBMがベースラインを
WAPEで上回ること等)を検証する(実データ・実API呼び出しは一切使用しない)。

## 現在のスコープ

ダミーデータ生成+需要予測モデル・週次forecast精度検証+補充ロジック・需要パターンの汎用化
(Streamlit UI)まで完了。人時・コスト換算、在庫コスト制約・複数拠点等のサプライチェーン構造、
GitHub Public公開作業は対象外。

## 公開について

GitHub Public公開前に、`pre-publish-anonymization-check`スキルで匿名化最終チェックを行う。
