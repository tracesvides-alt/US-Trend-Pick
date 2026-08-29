# US Trend Pick

個人利用向けの米国株トレンドランキングWebアプリです。
S&P 500、NASDAQ-100、Nasdaq Next Generation 100の構成銘柄を対象に、同じ条件で市場データを取得し、現在の市場で相対的に強い銘柄を毎週算出します。

常時100%株式を前提とし、弱くなった銘柄から相対的に強い銘柄へローテーションします。現金化、証券会社APIへの接続、株式の注文機能はありません。

## 機能

- SPY、QQQ、QQQJの公開保有銘柄から対象Universeを取得・統合
- `yfinance`による日足データ取得、チャンク処理、Retry、Parquet Cache
- データ欠損・履歴不足・ベンチマーク不足の検証
- Base Ranking
  - 12-1M Momentum
  - Dollar Volume Expansion
  - 週次リターンによるBeta
  - Cross-sectional Percentile
- Market Regime
  - NASDAQ100 Trend
  - S&P500 Trend
  - Market Breadth
  - Strategy Leadership
  - Volatility Regime
- Tactical Ranking
  - Relative Strength、RS Drawdown、移動平均、Stage 4判定
  - YTD、MTD、Weeklyリターン
- Primary Theme自動判定
  - Product / Service、Industry、Business Summary、Sector、End Marketの順に評価
  - 固定27 Theme Master、ドメイン固有Keyword、Confidence、Other fallback
  - AI / Cloud / Data Centerなどの汎用語だけではThemeを確定しない
  - 2回連続の週次判定でのみThemeを変更
- Theme Constraintを適用した10銘柄Portfolio Builder
- Pydanticで検証したFrontend用単一JSON
- 日本語中心のダークFinTech UI、モバイルBottom Navigation、ランキング検索・並べ替え
- GitHub Actionsによる週次実行と、成功時のみ行う静的Vercel Deploy

## アーキテクチャ

```text
公開Universeデータ
        ↓
Python Batch（取得・検証・計算）
        ↓
Parquet Cache / JSON / CSV
        ↓
Base → Market Regime → Tactical → Theme Classifier → Portfolio
        ↓
data/results/latest.json
        ↓
web/public/data/latest.json
        ↓
React PWA（静的表示）
```

ブラウザから市場データAPIへ直接アクセスしません。Frontendは生成済みの`latest.json`だけを読み込みます。データベースは使用しません。

## ディレクトリ

```text
engine/                 Pythonの取得・検証・ランキング・Portfolio処理
config/                 Primary Themeマスター、互換用設定、Ticker Alias
data/                   実行時に生成するCache・Snapshot・結果・Theme履歴
tests/                  Unit Test、Parser Fixture、Golden Fixture
web/                    React / TypeScript / Vite / PWA
.github/workflows/      GitHub Actions
```

`data/`配下のRuntime CSV、JSON、Parquetは`.gitignore`で除外しています。Frontendが配信する`web/public/data/latest.json`はWorkflowで生成し、成功したVercelの静的Deploy artifactへ含めます。Runtime結果を毎回Gitへ自動Commitする方式ではありません。

## Pythonセットアップ

Python 3.12を使用します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Runtime依存関係は`pandas`、`numpy`、`yfinance`、`requests`、`beautifulsoup4`、`pyyaml`、`pydantic`、`tenacity`、`pyarrow`です。開発用に`pytest`と`ruff`を使用します。

## Frontendセットアップ

```powershell
cd web
npm ci
npm run dev
```

ブラウザで表示するデータは`web/public/data/latest.json`です。Frontendから有料APIや市場データAPIには接続しません。

## 手動バッチ実行

リポジトリのルートで、次の順番に実行します。

```powershell
python -m engine.universe.builder
python -m engine.market_data.cache
python -m engine.ranking.base
python -m engine.ranking.regime
python -m engine.ranking.tactical
python -m engine.theme.classifier
python -m engine.portfolio.builder
python -m engine.results.builder
Copy-Item data/results/latest.json web/public/data/latest.json -Force
```

前回のMarket Regimeを指定する場合は、次のように実行します。

```powershell
python -m engine.ranking.regime --previous-state WARNING
```

主な生成物は次の通りです。

- `data/universe/YYYY-MM-DD.csv`: Universe Snapshot
- `data/market_data/prices.parquet`: 日足価格Cache
- `data/market_data/metadata.json`: 取得件数、失敗銘柄、Benchmark、データ状態
- `data/results/base-YYYY-MM-DD.json` / `.csv`: Base Ranking
- `data/results/regime-YYYY-MM-DD.json`: Market Regime
- `data/results/tactical-YYYY-MM-DD.json` / `.csv`: Tactical Ranking
- `data/themes/YYYY-MM-DD.json`: 計測日時点の全Universe Theme Snapshot
- `data/themes/history.json`: 自動管理されるTheme有効期間履歴
- `data/themes/theme-changes.json`: Theme変更履歴
- `data/themes/company-profiles.json`: 無料Company ProfileのCache
- `data/portfolio/YYYY-MM-DD.json`: Theme制約後のPortfolio
- `data/results/theme-review.json`: Tactical上位30銘柄のTheme状態（互換出力）
- `data/results/YYYY-MM-DD.json`: 日付付きFrontend用結果
- `data/results/latest.json`: 最新結果

## データ状態

対象Universeの必要データを1銘柄でも取得できない場合、推定で補完せず`INCOMPLETE`として扱います。

- `OFFICIAL`: 必要なUniverseデータが揃っている
- `INCOMPLETE`: 取得失敗、欠損、履歴不足、Benchmark不足などがある
- `RANKING_OFFICIAL_PORTFOLIO_PENDING`: 旧形式との互換用。自動Themeでは通常使用しない

Risk OFFでも現金化は行いません。RegimeはBase Scoreの配分を変更しますが、Portfolioは常時10銘柄・各10%を基本とします。

## Theme自動判定

Themeはランキング計算へ入力せず、Tactical Ranking完成後に自動判定します。

```text
Tactical Ranking → Primary Theme自動判定 → Theme Constraint → Portfolio確定
```

`config/themes.yaml`はClassifierが出力できるPrimary Themeの固定Masterです。ClassifierはMaster外の新しいTheme名を生成せず、判定材料が少ない場合は必ず`Other`へ分類します。

判定には無料のCompany Profile情報を使用します。優先順位はProduct / Service、Industry、Business Summary、Sector、End Marketです。会社名と過去Themeは補助情報に留めます。Yahoo Financeから取得したProfileは`data/themes/company-profiles.json`へCacheします。

`AI Cloud / Compute Infrastructure`はGPU Cloud、AI Compute Capacity、GPU-as-a-Serviceなど、計算資源そのものを提供する企業に限定します。AI Data Center向けの光学部品、Networking、Memory、Power、Security製品を販売する企業は、それぞれの製品Themeを優先します。

各銘柄について、`primary_theme`、`theme_score`、`second_theme`、`second_theme_score`、`confidence`（`HIGH` / `MEDIUM` / `LOW`）を保存します。Confidenceが`LOW`でもPortfolioを停止せず、最高ScoreのThemeを暫定Primary Themeとして使用します。

毎回の判定は`data/themes/YYYY-MM-DD.json`へPoint-in-Time Snapshotとして保存します。過去Snapshotを現在のランキングへ適用しません。既存Themeから別Themeへ変更する場合は、新Themeが2回連続の週次計測で優位になったときだけ変更し、旧履歴を終了して新しい期間を追加します。変更は`data/themes/theme-changes.json`へ保存し、Weekly Rotationとは分離して表示します。

通常運用で`config/theme_history.yaml`を編集する必要はありません。同ファイルは旧手動方式との互換用に残していますが、Portfolio Builderは同じ計測日の自動Snapshotだけを使用します。

Tickerのベンダー差異は`config/ticker_alias.yaml`で管理します。

```yaml
aliases:
  BRK.B: BRK-B
  BF.B: BF-B
```

Theme判定後は全銘柄にMaster内のThemeが付与されるため、Theme未設定を理由にPortfolio計算を停止しません。

## テスト・品質確認

Pythonの全テストと静的解析は次で実行します。

```powershell
pytest
ruff check .
python -c "import engine; import engine.init; print('engine import ok')"
```

Frontendは次で型チェック、Unit Test、本番ビルド、PWA生成をまとめて確認します。

```powershell
cd web
npm run check
```

外部通信を必要とする取得処理はUnit Testから分離し、Parser・計算式・欠損判定・Golden FixtureをローカルFixtureで検証します。

## GitHub Actions

`.github/workflows/weekly-ranking.yml`を使用します。

- 定期実行: 毎週土曜日08:17 JST相当（`17 23 * * 5` UTC）
- 手動実行: `workflow_dispatch`
- 実行順: Universe → Market Data → Validation → Base → Regime → Tactical → Theme → Portfolio → Result JSON → pytest → ruff → Frontend Build → Deploy
- 取得失敗や検証失敗時はWorkflowを失敗扱いにし、不完全な結果で正常終了しません
- ログにAs Of、Universe件数、取得成功・失敗、Ranking状態を出力
- CacheはGitHub Actions Cacheへ保存

Vercel Deployには次のGitHub Secretsを使用します。値をソースコードへ記述しません。

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Ranking、テスト、Frontend Buildがすべて成功した場合のみ、静的React PWAをVercelへDeployします。失敗時は前回の正常版を維持します。

## 既知の制約

- 無料データソースの仕様変更、レート制限、通信障害の影響を受けます
- `yfinance`で取得できない銘柄は推定補完せず、データ状態を`INCOMPLETE`にします
- Delisted銘柄、Ticker変更、Corporate Actionの履歴は無料データの品質に依存します
- 日中更新ではなく、週次バッチで生成した結果を表示します
- 売買注文、証券会社連携、現金化、通知機能はありません

## 障害時の復旧

1. GitHub Actionsの失敗ステップとPipeline Summaryを確認します。
2. `As Of`、Universe件数、取得失敗銘柄、Benchmark sourceを確認します。
3. 必要に応じてWorkflowを`workflow_dispatch`で再実行します。
4. Theme関連の場合は`data/themes`のSnapshot、Profile Cache、`theme-changes.json`を確認して再実行します。
5. 失敗したWorkflowではDeployされないため、Vercel上の前回正常版が維持されます。

## 運用方針

本アプリは個人利用向けのリサーチ補助ツールです。ランキングは投資助言や売買推奨を目的とせず、データ取得状況と計算結果を確認したうえで利用してください。
