import { useEffect, useMemo, useState } from "react";
import type { ColumnDef, SortingFn, SortingState } from "@tanstack/react-table";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  activePortfolio,
  displayRegime,
  formatDate,
  formatPercent,
  formatRank,
  formatScore,
  formatStatus,
  getTacticalStatus,
  isThemeReviewRequired,
  numberOrNull,
  regimeScore,
  stockRankHistory,
  type Movement,
  type NullableNumber,
  type RankRow,
  type ResultDocument,
  type ThemeReviewRow,
  type TacticalRow,
} from "./lib/dashboard";

type View = "dashboard" | "detail";
type NavTarget = "home" | "tactical" | "base" | "history" | "settings";
type IconName = "home" | "tactical" | "base" | "history" | "settings" | "arrow" | "search";

const numberClass = "tabular-nums";
const navItems: Array<{ target: NavTarget; label: string; icon: IconName }> = [
  { target: "home", label: "ホーム", icon: "home" },
  { target: "tactical", label: "Tactical", icon: "tactical" },
  { target: "base", label: "Base", icon: "base" },
  { target: "history", label: "履歴", icon: "history" },
  { target: "settings", label: "設定", icon: "settings" },
];

const rankSorting: SortingFn<TacticalRow> = (rowA, rowB, columnId) => {
  const a = numberOrNull(rowA.getValue(columnId) as number | null);
  const b = numberOrNull(rowB.getValue(columnId) as number | null);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
};

function toneForStatus(status: string): string {
  const normalized = status.toUpperCase();
  if (["OFFICIAL", "CONFIRMED", "COMPLETE", "RISK_ON", "ENTRY"].includes(normalized)) {
    return "tone-positive";
  }
  if (
    normalized.includes("PENDING") ||
    normalized.includes("REVIEW") ||
    normalized === "WARNING" ||
    normalized === "RANKING_OFFICIAL_PORTFOLIO_PENDING" ||
    normalized === "HOLD"
  ) {
    return "tone-warning";
  }
  if (["UNKNOWN", "UNRANKED", "未採用"].includes(normalized)) return "tone-neutral";
  return "tone-negative";
}

function toneForReturn(value: NullableNumber): string {
  const number = numberOrNull(value);
  if (number === null || number === 0) return "return-neutral";
  return number > 0 ? "return-positive" : "return-negative";
}

function returnWithTone(value: NullableNumber) {
  return <span className={`${numberClass} ${toneForReturn(value)}`}>{formatPercent(value)}</span>;
}

function stageLabel(stage: string | undefined): string {
  if (stage === "Normal") return "通常";
  if (stage === "Unknown") return "不明";
  return stage ?? "不明";
}

function rankLabel(value: NullableNumber): string {
  const rank = formatRank(value);
  return rank === "—" ? "—" : `#${rank}`;
}

function tacticalStatusLabel(status: string): string {
  return status === "Unranked" ? "対象外" : status;
}

function recordScore(record: unknown, key: string): number | null {
  if (!record || typeof record !== "object") return null;
  const value = (record as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, string> = {
    home: "M3 10.5 12 3l9 7.5M5.5 9v10h13V9M9 19v-5h6v5",
    tactical: "M4 18V8m5 10V4m5 14v-7m5 7V6",
    base: "M4 5h16v14H4zM8 9h8M8 13h5M8 17h3",
    history: "M4 12a8 8 0 1 0 2.35-5.65M4 5v4h4M12 7v5l3 2",
    settings: "M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Zm0-5v2m0 13.6v2M3.5 12h2m13 0h2M5.95 5.95l1.4 1.4m9.3 9.3 1.4 1.4m0-12.1-1.4 1.4m-9.3 9.3-1.4 1.4",
    arrow: "M5 12h13m-5-5 5 5-5 5",
    search: "m20 20-4.2-4.2M10.8 17a6.2 6.2 0 1 0 0-12.4 6.2 6.2 0 0 0 0 12.4Z",
  };
  return (
    <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d={paths[name]} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function App() {
  const [result, setResult] = useState<ResultDocument | null>(null);
  const [error, setError] = useState(false);
  const [view, setView] = useState<View>("dashboard");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [activeNav, setActiveNav] = useState<NavTarget>("home");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/data/latest.json", { cache: "no-store", signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("result unavailable");
        return response.json() as Promise<ResultDocument>;
      })
      .then(setResult)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(true);
      });
    return () => controller.abort();
  }, []);

  const navigate = (target: NavTarget) => {
    setActiveNav(target);
    setView("dashboard");
    window.setTimeout(() => {
      document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  };

  const openDetail = (ticker: string) => {
    setSelectedTicker(ticker);
    setView("detail");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (error) return <ErrorState />;
  if (!result) return <LoadingState />;

  return (
    <div className="app-shell">
      <Header result={result} onDashboard={() => navigate("home")} />
      <div className="app-body">
        <Sidebar activeNav={activeNav} onNavigate={navigate} />
        <div className="app-content">
          {view === "detail" && selectedTicker ? (
            <StockDetail result={result} ticker={selectedTicker} onBack={() => navigate("home")} />
          ) : (
            <Dashboard result={result} onSelectTicker={openDetail} onNavigate={navigate} />
          )}
        </div>
      </div>
      <MobileNavigation activeNav={activeNav} onNavigate={navigate} />
      <footer className="app-footer">個人利用向けリサーチダッシュボード　・　注文機能なし　・　常時100%株式</footer>
    </div>
  );
}

function Header({ result, onDashboard }: { result: ResultDocument; onDashboard: () => void }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button className="brand" onClick={onDashboard} aria-label="ダッシュボードを開く">
          <span className="brand-mark"><span>UT</span></span>
          <span className="brand-copy">
            <strong>US Trend Pick</strong>
            <small>週次 相対強度ランキング</small>
          </span>
        </button>
        <div className="topbar-meta">
          <span className="updated-label">最終更新　{formatDate(result.asOf)}</span>
          <span className={`status-pill ${toneForStatus(result.status)}`}>
            <span className="status-dot" />{formatStatus(result.status)}
          </span>
        </div>
      </div>
    </header>
  );
}

function Sidebar({ activeNav, onNavigate }: { activeNav: NavTarget; onNavigate: (target: NavTarget) => void }) {
  return (
    <aside className="sidebar" aria-label="メインナビゲーション">
      <p className="sidebar-label">ナビゲーション</p>
      <nav>
        {navItems.map((item) => (
          <button
            key={item.target}
            className={`nav-item ${activeNav === item.target ? "is-active" : ""}`}
            onClick={() => onNavigate(item.target)}
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-note">
        <span className="live-dot" />
        <span>週次データ<br /><small>生成済みJSONを表示</small></span>
      </div>
    </aside>
  );
}

function MobileNavigation({ activeNav, onNavigate }: { activeNav: NavTarget; onNavigate: (target: NavTarget) => void }) {
  return (
    <nav className="mobile-nav" aria-label="モバイルナビゲーション">
      {navItems.map((item) => (
        <button key={item.target} className={`mobile-nav-item ${activeNav === item.target ? "is-active" : ""}`} onClick={() => onNavigate(item.target)}>
          <Icon name={item.icon} size={18} />
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}

function Dashboard({ result, onSelectTicker, onNavigate }: { result: ResultDocument; onSelectTicker: (ticker: string) => void; onNavigate: (target: NavTarget) => void }) {
  const holdings = activePortfolio(result.portfolio);
  const score = regimeScore(result.marketRegime);
  const tacticalByTicker = useMemo(
    () => Object.fromEntries(result.tacticalRanking.map((row) => [row.ticker, row])),
    [result.tacticalRanking],
  );
  const topTactical = useMemo(
    () => result.tacticalRanking.filter((row) => numberOrNull(row.tactical_rank) !== null),
    [result.tacticalRanking],
  );
  const themeReviewRequired = useMemo(
    () => result.themeReview.filter(isThemeReviewRequired),
    [result.themeReview],
  );
  const rotationChanged = result.rotation.portfolioIn.length + result.rotation.portfolioOut.length;

  return (
    <main className="page-container" id="home">
      <section className="intro-panel">
        <div className="intro-copy">
          <p className="eyebrow">週次ランキング / 米国株</p>
          <h1>いま強い銘柄を、<br /><span>毎週見つける。</span></h1>
          <p>市場レジームと相対強度を組み合わせ、現在の市場で相対的に強い銘柄を確認します。</p>
        </div>
        <div className="intro-actions">
          <button className="button button-primary" onClick={() => onNavigate("tactical")}>Tacticalを見る <Icon name="arrow" size={16} /></button>
          <button className="button button-secondary" onClick={() => onNavigate("base")}>Baseを見る</button>
        </div>
      </section>

      <section className="regime-panel panel panel-highlight" aria-labelledby="regime-title">
        <div className="panel-heading regime-heading">
          <div>
            <p className="eyebrow">市場レジーム</p>
            <h2 id="regime-title">市場レジーム</h2>
          </div>
          <span className={`regime-badge ${toneForStatus(displayRegime(result.marketRegime))}`}>
            {displayRegime(result.marketRegime)}
          </span>
        </div>
        <div className="regime-body">
          <div className="regime-score-block">
            <span className="metric-label">レジームスコア</span>
            <strong className={`regime-score ${toneForStatus(displayRegime(result.marketRegime))} ${numberClass}`}>{score === null ? "—" : score.toFixed(1)}</strong>
            <span className="metric-detail">70以上 Risk ON / 41–69 Warning / 40以下 Risk OFF</span>
          </div>
          <div className="regime-components">
            <RegimeComponent label="NASDAQ100トレンド" value={recordScore((result.marketRegime as Record<string, unknown>).component_scores, "nasdaq100_trend")} />
            <RegimeComponent label="S&P500トレンド" value={recordScore((result.marketRegime as Record<string, unknown>).component_scores, "sp500_trend")} />
            <RegimeComponent label="市場の広がり" value={recordScore((result.marketRegime as Record<string, unknown>).component_scores, "market_breadth")} />
            <RegimeComponent label="戦略リーダーシップ" value={recordScore((result.marketRegime as Record<string, unknown>).component_scores, "strategy_leadership")} />
            <RegimeComponent label="ボラティリティ" value={recordScore((result.marketRegime as Record<string, unknown>).component_scores, "volatility_regime")} />
          </div>
        </div>
      </section>

      <section className="summary-grid" aria-label="サマリー">
        <MetricCard label="データ状態" value={formatStatus(result.dataHealth.status)} detail={`${result.dataHealth.missing_tickers.length}銘柄を確認中`} tone={toneForStatus(result.dataHealth.status)} />
        <MetricCard label="採用銘柄" value={`${holdings.length} / 10`} detail={formatStatus(result.portfolioStatus)} tone={toneForStatus(result.portfolioStatus)} />
        <MetricCard label="今週の変動" value={`${rotationChanged} IN / OUT`} detail={`${result.rotation.hold.length} HOLD`} tone="tone-neutral" />
        <MetricCard label="対象銘柄" value={String(result.dataHealth.universe_count)} detail={`Tactical有効 ${result.dataHealth.tactical_eligible_count}`} tone="tone-accent" />
      </section>

      <section className="content-grid" id="portfolio">
        <div className="panel panel-wide">
          <SectionHeading title="採用10銘柄" kicker="採用銘柄 / 10%均等配分" />
          {holdings.length > 0 ? (
            <div className="portfolio-grid">
              {holdings.map((holding) => {
                const tactical = tacticalByTicker[holding.ticker];
                return (
                  <button className="holding-card" key={holding.ticker} onClick={() => onSelectTicker(holding.ticker)} aria-label={`${holding.ticker}の詳細を開く`}>
                    <div className="holding-topline">
                      <span className="ticker-label">{holding.ticker}</span>
                      <span className={`mini-pill ${toneForStatus(holding.status ?? "")}`}>{formatStatus(holding.status)}</span>
                    </div>
                    <span className="holding-theme">{holding.theme ?? "テーマ未設定"}</span>
                    <div className="holding-ranks">
                      <span><small>Tactical</small><strong className="rank-emphasis">{rankLabel(holding.tactical_rank)}</strong></span>
                      <span><small>Base</small><strong>{rankLabel(holding.base_rank)}</strong></span>
                      <span><small>健全度</small><strong className={numberClass}>{formatScore(tactical?.health)}</strong></span>
                    </div>
                    <div className="holding-returns">
                      <span><small>YTD</small>{returnWithTone(holding.ytd)}</span>
                      <span><small>MTD</small>{returnWithTone(holding.mtd)}</span>
                      <span><small>Weekly</small>{returnWithTone(holding.weekly)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <ReviewNotice rows={themeReviewRequired} />
          )}
        </div>

        <div className="panel" id="rotation">
          <SectionHeading title="今週のローテーション" kicker="週次ローテーション / 前回比較" />
          <RotationPanel result={result} onSelectTicker={onSelectTicker} />
        </div>
      </section>

      <ThemeReviewPanel rows={result.themeReview} onSelectTicker={onSelectTicker} />

      <section className="panel" id="tactical">
        <SectionHeading title="Tacticalランキング" kicker={`${topTactical.length}銘柄が計算対象 / 並べ替え・検索`} />
        <TacticalTable result={result} onSelectTicker={onSelectTicker} />
      </section>

      <section className="panel" id="base">
        <SectionHeading title="Baseランキング" kicker={`上位${Math.min(20, result.baseRanking.length)}銘柄 / 中立Base`} />
        <BaseTable rows={result.baseRanking.slice(0, 20)} onSelectTicker={onSelectTicker} />
      </section>

      <HistoryPanel result={result} onSelectTicker={onSelectTicker} />
      <DataHealthPanel result={result} />
      <SettingsPanel result={result} />
    </main>
  );
}

function RegimeComponent({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="regime-component">
      <span>{label}</span>
      <strong className={numberClass}>{formatScore(value)}</strong>
      <div className="score-track"><span style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} /></div>
    </div>
  );
}

function MetricCard({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: string }) {
  return (
    <article className="metric-card">
      <span className="metric-label">{label}</span>
      <strong className={`metric-value ${tone}`}>{value}</strong>
      <span className="metric-detail">{detail}</span>
    </article>
  );
}

function SectionHeading({ title, kicker }: { title: string; kicker: string }) {
  return (
    <div className="section-heading">
      <div><p className="eyebrow">{kicker}</p><h2>{title}</h2></div>
    </div>
  );
}

function ReviewNotice({ rows }: { rows: ThemeReviewRow[] }) {
  return (
    <div className="review-notice">
      <div className="notice-icon">!</div>
      <div>
        <strong>テーマ設定待ちのため採用銘柄を確認中です</strong>
        <p>{rows.length > 0 ? `Tactical上位30銘柄のうち${rows.length}銘柄にTheme設定がありません。` : "採用候補を確定できるデータがまだありません。"} テーマ確認後にPortfolioを確定します。</p>
        <div className="review-tickers">
          {rows.slice(0, 10).map((row) => <span key={row.ticker}>{row.ticker}</span>)}
          {rows.length > 10 && <span>+{rows.length - 10}</span>}
        </div>
      </div>
    </div>
  );
}

function ThemeReviewPanel({ rows, onSelectTicker }: { rows: ThemeReviewRow[]; onSelectTicker: (ticker: string) => void }) {
  const pending = rows.filter(isThemeReviewRequired);
  return (
    <section className="panel theme-review-panel" id="theme-review">
      <SectionHeading title="テーマ設定待ち" kicker={`Tactical上位${rows.length || 30}銘柄 / Git管理で手動設定`} />
      {pending.length > 0 ? (
        <>
          <p className="theme-review-help">Themeは自動確定しません。<code>config/theme_history.yaml</code>を更新し、GitHub Actionsを再実行してください。</p>
          <div className="theme-review-list">
            {pending.map((row) => (
              <button className="theme-review-row" key={row.ticker} onClick={() => onSelectTicker(row.ticker)}>
                <span className="theme-review-main"><strong>{row.ticker}</strong><small>{row.company_name ?? "企業名未取得"}</small></span>
                <span className="theme-review-ranks"><small>Tactical / Base</small><strong>{rankLabel(row.tactical_rank)} / {rankLabel(row.base_rank)}</strong></span>
                <span className="theme-review-sector"><small>{row.sector ?? "セクター未取得"}</small><span>{row.industry ?? "業種未取得"}</span></span>
                <span className="mini-pill tone-warning">テーマ設定待ち</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state compact-empty"><span className="empty-mark">✓</span><strong>テーマ設定待ちはありません</strong><small>上位30銘柄のThemeが確認済みです</small></div>
      )}
    </section>
  );
}

function RotationPanel({ result, onSelectTicker }: { result: ResultDocument; onSelectTicker: (ticker: string) => void }) {
  const hasChange = result.rotation.portfolioIn.length + result.rotation.portfolioOut.length > 0;
  const hasAny = hasChange || result.rotation.hold.length > 0;
  return (
    <div className="rotation-panel">
      {!hasChange && <div className="rotation-empty"><span className="empty-mark">—</span><strong>今週の入れ替えはありません</strong><small>前回の採用銘柄との比較</small></div>}
      {hasAny && (
        <div className="movement-stack">
          <MovementList label="IN" rows={result.rotation.portfolioIn} tone="positive" onSelectTicker={onSelectTicker} />
          <MovementList label="OUT" rows={result.rotation.portfolioOut} tone="negative" onSelectTicker={onSelectTicker} />
          <MovementList label="HOLD" rows={result.rotation.hold} tone="neutral" onSelectTicker={onSelectTicker} />
        </div>
      )}
    </div>
  );
}

function MovementList({ label, rows, tone, onSelectTicker }: { label: string; rows: Movement[]; tone: string; onSelectTicker: (ticker: string) => void }) {
  return (
    <div className="movement-group">
      <div className="movement-heading"><span className={`movement-dot ${tone}`} />{label}<span>{rows.length}</span></div>
      {rows.length > 0 ? rows.slice(0, 5).map((row) => (
        <button className="movement-row" key={row.ticker} onClick={() => onSelectTicker(row.ticker)}>
          <span className="movement-ticker">{row.ticker}</span>
          <span className="movement-path">{rankPath(row.previousRank, row.currentRank)}</span>
        </button>
      )) : <p className="empty-copy compact">該当なし</p>}
    </div>
  );
}

function rankPath(previous: NullableNumber, current: NullableNumber): string {
  const oldRank = formatRank(previous);
  const newRank = formatRank(current);
  if (oldRank === "—" && newRank === "—") return "—";
  return `${oldRank === "—" ? "—" : `#${oldRank}`} → ${newRank === "—" ? "—" : `#${newRank}`}`;
}

function BaseTable({ rows, onSelectTicker }: { rows: RankRow[]; onSelectTicker: (ticker: string) => void }) {
  return (
    <div className="table-scroll">
      <table className="data-table compact-table">
        <thead><tr><th>順位</th><th className="ticker-header">Ticker</th><th>Base</th><th>Momentum</th><th>売買代金</th><th>Beta</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ticker}>
              <td className={numberClass}>{formatRank(row.base_rank)}</td>
              <td className="ticker-cell"><button className="ticker-button" onClick={() => onSelectTicker(row.ticker)}>{row.ticker}</button></td>
              <td className={numberClass}>{formatScore(row.base_score)}</td>
              <td className={numberClass}>{formatScore(row.momentum_score)}</td>
              <td className={numberClass}>{formatScore(row.volume_score)}</td>
              <td className={numberClass}>{formatScore(row.beta_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TacticalTable({ result, onSelectTicker }: { result: ResultDocument; onSelectTicker: (ticker: string) => void }) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "tactical_rank", desc: false }]);
  const themeByTicker = useMemo(() => {
    const map: Record<string, string> = {};
    result.themeReview.forEach((row) => { if (row.current_theme) map[row.ticker] = row.current_theme; });
    result.portfolio.forEach((row) => { if (row.theme) map[row.ticker] = row.theme; });
    return map;
  }, [result.portfolio, result.themeReview]);
  const rows = useMemo<TacticalRow[]>(() => result.tacticalRanking.map((row) => ({
    ...row,
    theme: themeByTicker[row.ticker] ?? null,
    status: getTacticalStatus(row),
  })), [result.tacticalRanking, themeByTicker]);
  const columns = useMemo<ColumnDef<TacticalRow>[]>(() => [
    { accessorKey: "tactical_rank", header: "Tactical", sortUndefined: "last", sortingFn: rankSorting, cell: ({ getValue }) => <span className="rank-cell">{formatRank(getValue() as number | null)}</span> },
    { accessorKey: "base_rank", header: "Base", sortUndefined: "last", sortingFn: rankSorting, cell: ({ getValue }) => formatRank(getValue() as number | null) },
    { accessorKey: "rank_change", header: "順位差", cell: ({ getValue }) => formatRank(getValue() as number | null) },
    { accessorKey: "ticker", header: "Ticker", cell: ({ row }) => <button className="ticker-button" onClick={() => onSelectTicker(row.original.ticker)}>{row.original.ticker}</button> },
    { id: "theme", accessorFn: (row) => row.theme ?? "", header: "テーマ", cell: ({ getValue }) => String(getValue()) || "未設定" },
    { accessorKey: "tactical_score", header: "Tacticalスコア", cell: ({ getValue }) => formatScore(getValue() as number | null) },
    { accessorKey: "health", header: "健全度", cell: ({ getValue }) => formatScore(getValue() as number | null) },
    { accessorKey: "ytd", header: "YTD", cell: ({ getValue }) => returnWithTone(getValue() as number | null) },
    { accessorKey: "mtd", header: "MTD", cell: ({ getValue }) => returnWithTone(getValue() as number | null) },
    { accessorKey: "weekly", header: "Weekly", cell: ({ getValue }) => returnWithTone(getValue() as number | null) },
    { accessorKey: "stage", header: "Stage", cell: ({ getValue }) => stageLabel(getValue() as string | undefined) },
    { accessorKey: "status", header: "状態", cell: ({ getValue }) => <span className={`mini-pill ${toneForStatus(String(getValue()))}`}>{tacticalStatusLabel(String(getValue()))}</span> },
  ], [onSelectTicker]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const visibleRows = table.getRowModel().rows;

  return (
    <>
      <div className="table-toolbar">
        <label className="search-box"><Icon name="search" size={16} /><input value={globalFilter} onChange={(event) => setGlobalFilter(event.target.value)} placeholder="Tickerを検索" aria-label="Tickerを検索" /></label>
        <span className="table-count">{visibleRows.length} / {rows.length} 件</span>
      </div>
      <div className="table-scroll">
        <table className="data-table tactical-table">
          <thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} className={header.column.id === "ticker" ? "ticker-header" : ""}><button className={header.column.getCanSort() ? "sort-button" : "sort-button disabled"} onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}>{flexRender(header.column.columnDef.header, header.getContext())}{header.column.getIsSorted() === "asc" ? " ↑" : header.column.getIsSorted() === "desc" ? " ↓" : ""}</button></th>)}</tr>)}</thead>
          <tbody>
            {visibleRows.map((row) => <tr key={row.id}>{row.getVisibleCells().map((cell) => <td key={cell.id} className={cell.column.id === "ticker" ? "ticker-cell" : ""}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}
            {visibleRows.length === 0 && <tr><td className="table-empty" colSpan={columns.length}>該当するTickerがありません</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function HistoryPanel({ result, onSelectTicker }: { result: ResultDocument; onSelectTicker: (ticker: string) => void }) {
  const changes = result.rotation.rankChange.filter((row) => row.previousRank !== null && row.previousRank !== undefined).slice(0, 10);
  return (
    <section className="panel" id="history">
      <SectionHeading title="ランキング履歴" kicker="履歴 / 前回からの順位変化" />
      {changes.length > 0 ? (
        <div className="history-list">
          {changes.map((row) => {
            const change = numberOrNull(row.rankChange);
            return <button className="history-row" key={row.ticker} onClick={() => onSelectTicker(row.ticker)}><span className="history-ticker">{row.ticker}</span><span className="history-path">{rankPath(row.previousRank, row.currentRank)}</span><span className={`history-change ${change !== null && change > 0 ? "return-positive" : change !== null && change < 0 ? "return-negative" : "return-neutral"}`}>{change === null ? "—" : `${change > 0 ? "+" : ""}${formatRank(change)}`}</span></button>;
          })}
        </div>
      ) : <div className="empty-state"><span className="empty-mark">—</span><strong>まだ比較できる履歴がありません</strong><small>次回の週次更新から順位変化を表示します</small></div>}
    </section>
  );
}

function DataHealthPanel({ result }: { result: ResultDocument }) {
  const health = result.dataHealth;
  return (
    <section className="panel data-health" id="health">
      <SectionHeading title="データ取得状況" kicker="データ状態 / 計算前の完全性確認" />
      <div className="health-grid">
        <HealthItem label="対象銘柄" value={`${health.universe_count}`} detail="取得対象" />
        <HealthItem label="Base有効" value={`${health.base_eligible_count}`} detail="ランキング対象" />
        <HealthItem label="Tactical有効" value={`${health.tactical_eligible_count}`} detail="ランキング対象" />
        <HealthItem label="確認対象" value={`${health.missing_tickers.length}`} detail="欠損 / 履歴不足" />
      </div>
      <div className="health-footer"><span>キャッシュ　{formatStatus(health.cache_data_status)}</span><span>レジーム　{formatStatus(health.regime_data_status)}</span><span>ベンチマーク　{Object.values(health.benchmark_sources).join(" / ") || "未取得"}</span></div>
    </section>
  );
}

function HealthItem({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="health-item"><span>{label}</span><strong className={numberClass}>{value}</strong><small>{detail}</small></div>;
}

function SettingsPanel({ result }: { result: ResultDocument }) {
  return (
    <section className="panel settings-panel" id="settings">
      <SectionHeading title="設定" kicker="表示と運用方針" />
      <div className="settings-grid">
        <div><span>運用方針</span><strong>常時100%株式</strong><small>現金化・注文機能はありません</small></div>
        <div><span>データ接続</span><strong>生成済みJSONのみ</strong><small>ブラウザから市場データAPIへ接続しません</small></div>
        <div><span>現在の状態</span><strong className={toneForStatus(result.status)}>{formatStatus(result.status)}</strong><small>最終更新 {formatDate(result.asOf)}</small></div>
      </div>
    </section>
  );
}

function StockDetail({ result, ticker, onBack }: { result: ResultDocument; ticker: string; onBack: () => void }) {
  const tactical = result.tacticalRanking.find((row) => row.ticker === ticker);
  const base = result.baseRanking.find((row) => row.ticker === ticker);
  const holding = result.portfolio.find((row) => row.ticker === ticker);
  const history = stockRankHistory(ticker, result);
  if (!tactical && !base) return <main className="page-container detail-page"><button className="back-button" onClick={onBack}>← ダッシュボードに戻る</button><div className="panel empty-state"><strong>銘柄が見つかりません</strong><small>現在の結果JSONに該当Tickerがありません</small></div></main>;

  const currentStatus = tactical ? getTacticalStatus(tactical) : "Unranked";
  return (
    <main className="page-container detail-page">
      <button className="back-button" onClick={onBack}>← ダッシュボードに戻る</button>
      <section className="detail-hero">
        <div><p className="eyebrow">銘柄詳細 / {formatDate(result.asOf)}</p><h1>{ticker}</h1><p>{holding?.theme ?? "テーマ未設定"}</p></div>
        <span className={`status-pill ${toneForStatus(currentStatus)}`}>{tacticalStatusLabel(currentStatus)}</span>
      </section>
      <section className="detail-grid">
        <div className="panel chart-panel"><SectionHeading title="ランキング履歴" kicker="前回と今回のTactical順位" /><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><LineChart data={history} margin={{ top: 12, right: 10, left: -20, bottom: 4 }}><CartesianGrid strokeDasharray="3 3" stroke="#263244" /><XAxis dataKey="period" stroke="#718096" tickLine={false} axisLine={false} /><YAxis reversed allowDecimals={false} stroke="#718096" tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: "#151b27", border: "1px solid rgba(255,255,255,.1)", borderRadius: 10 }} labelStyle={{ color: "#f5f7fa" }} /><Line type="monotone" dataKey="tacticalRank" name="Tactical" stroke="#4cc9f0" strokeWidth={2.5} dot={{ r: 4, fill: "#4cc9f0", stroke: "#080b12", strokeWidth: 2 }} connectNulls /></LineChart></ResponsiveContainer></div></div>
        <div className="panel detail-stats"><SectionHeading title="スナップショット" kicker="現在値" /><DetailStat label="Tactical順位" value={rankLabel(tactical?.tactical_rank)} accent /><DetailStat label="Base順位" value={rankLabel(tactical?.base_rank ?? base?.base_rank)} /><DetailStat label="Tacticalスコア" value={formatScore(tactical?.tactical_score)} /><DetailStat label="健全度" value={formatScore(tactical?.health)} /><DetailStat label="YTD / MTD" value={`${formatPercent(tactical?.ytd)} / ${formatPercent(tactical?.mtd)}`} /><DetailStat label="Weekly" value={formatPercent(tactical?.weekly)} /><DetailStat label="Stage" value={stageLabel(tactical?.stage)} /><DetailStat label="採用状態" value={holding ? formatStatus(holding.status) : "未採用"} /></div>
      </section>
    </main>
  );
}

function DetailStat({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className="detail-stat"><span>{label}</span><strong className={`${accent ? "accent-text" : ""} ${numberClass}`}>{value}</strong></div>;
}

function LoadingState() {
  return <div className="state-screen" role="status" aria-label="ランキング結果を読み込み中"><div className="loading-card"><div className="skeleton skeleton-logo" /><div className="skeleton skeleton-title" /><div className="skeleton skeleton-line" /><div className="skeleton-grid"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div></div><p>ランキング結果を読み込んでいます…</p></div>;
}

function ErrorState() {
  return <div className="state-screen"><div className="error-mark">!</div><h1>データを表示できません</h1><p>ランキング結果の読み込みに失敗しました。</p><p className="empty-copy">データ取得状況を確認してから、もう一度お試しください。</p></div>;
}

export default App;
