# US Trend Pick

## Phase 2: Market Data Cache

Phase 2 downloads daily OHLC, adjusted-close equivalent, and volume data for the complete Universe in chunks via `yfinance`. The normalized long-format data is merged into a Parquet cache, with run status and benchmark source selection stored in a JSON sidecar.

```powershell
python -m engine.market_data.cache
```

The batch uses `^GSPC` and `^NDX` when available, and can fall back to `SPY` and `QQQ`. A failed Universe ticker or insufficient history is retained in metadata and makes the run `INCOMPLETE`.

## Phase 3: Base Trend Ranking

Phase 3 calculates 12-1M adjusted-price momentum, raw dollar-volume expansion, weekly-return beta, cross-sectional percentile scores, and the weighted Base Score for the full Universe.

```powershell
python -m engine.ranking.base
```

The batch writes `data/results/base-YYYY-MM-DD.json` and `.csv`, prints the Top20, and reports excluded tickers by reason. Tactical Ranking, Theme, Portfolio, and Web UI are not included yet.

## Phase 4: Market Regime

Phase 4 reads the existing Base Ranking, price cache, and Universe source flags to calculate the weighted Market Regime components, hysteresis, and Stage 4 overrides.

```powershell
python -m engine.ranking.regime
python -m engine.ranking.regime --previous-state WARNING
```

The result is written to `data/results/regime-YYYY-MM-DD.json`. The JSON records every component score, benchmark source, breadth ratios, stage flags, and data completeness status.

## Phase 5: Tactical Ranking

Phase 5 reads the existing Base Ranking and Market Regime, calculates Tactical Health, penalties, Stage 4, New Buy, and YTD/MTD/weekly returns for the full Universe.

```powershell
python -m engine.ranking.tactical
```

The batch writes `data/results/tactical-YYYY-MM-DD.json` and `.csv`, prints the Top30, and keeps data-insufficient Universe rows as unranked records rather than estimating their scores.

## Phase 6: Theme and Portfolio Builder

Phase 6 loads time-effective Theme records from `config/theme_history.yaml`, applies the Theme Constraint only during Portfolio construction, and reads the previous portfolio when available.

```powershell
python -m engine.portfolio.builder
```

The batch writes `data/portfolio/YYYY-MM-DD.json`. Unclassified Tactical Top20 candidates produce `THEME_REVIEW_REQUIRED`; no GitHub Issue is created automatically.

## Phase 7: Frontend Result JSON and History

Phase 7 combines the existing Base Ranking, Tactical Ranking, Market Regime, data-health metadata, and Portfolio output into one Pydantic-validated document. The dated history and `latest.json` are written only after validation succeeds. Weekly rank changes and Portfolio IN/OUT/HOLD transitions are calculated from the previous dated result.

```powershell
python -m engine.results.builder
```

The batch writes `data/results/YYYY-MM-DD.json` and `data/results/latest.json`. If market-data or ranking completeness is not official, the result is `INCOMPLETE`; if only Theme/Portfolio confirmation is pending, the result is `RANKING_OFFICIAL_PORTFOLIO_PENDING`.

## Phase 9: Weekly GitHub Actions

`.github/workflows/weekly-ranking.yml` runs the Universe, Market Data, Validation, Base, Regime, Tactical, Portfolio, unified JSON, Python tests, Ruff, and Frontend PWA build in order. It runs every Friday at 23:17 UTC (Saturday 08:17 JST) and can also be started with `workflow_dispatch`. Market-data download failures stop the job before ranking output.

## Phase 10: Vercel Deploy

After the ranking pipeline, tests, and Frontend build succeed, the same Workflow runs a static Vite deployment from `web/` with `vercel build` and `vercel deploy --prebuilt --prod`. Configure `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` as GitHub Actions Secrets; they are never stored in the repository. A failed step keeps the previous production deployment active.

個人利用向けの米国株ランキングWebアプリです。S&P 500、NASDAQ-100、Nasdaq Next Generation 100の構成銘柄を対象に、市場データをPythonでバッチ処理し、相対的に強い銘柄を毎週算出して表示することを目的とします。

現在はPhase 1です。3つの対象Universeを無料公開データから取得し、正規化・重複除去したCSV Snapshotを生成できます。価格取得、ランキング計算、Web画面はまだ実装していません。市場データはフロントエンドから直接取得せず、将来生成するJSONをReact PWAから読み込む構成とします。

## Pythonセットアップ

Python 3.12を用意し、リポジトリのルートで仮想環境を作成します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Test方法

```powershell
pytest
ruff check .
python -c "import engine; import engine.init; print('engine import ok')"
```

## Universe Snapshot生成

```powershell
python -m engine.universe.builder
```

取得したSPY、QQQ、QQQJを統合し、`data/universe/YYYY-MM-DD.csv`へ保存します。取得先が部分データの場合は採用せず、Fallback失敗も実行結果に表示します。

テストは外部APIや市場データに依存しない形で実行します。データ不足を推定で補う処理や、有料API・証券会社APIへの接続は行いません。

## 今後のPhase概要

1. Universeと市場データ取得・キャッシュの基盤
2. Base Trend RankingとTactical Rankingの計算
3. Market Regime、Theme Constraint、Portfolio Builder
4. JSON生成バッチとGitHub Actions自動実行
5. React / TypeScript / Viteによるランキング表示とPWA化
6. 結合テスト、データ不足時のINCOMPLETE判定、Vercel公開準備

各Phaseで要件、実装、自動テスト、実行確認を完了してから次のPhaseへ進みます。
