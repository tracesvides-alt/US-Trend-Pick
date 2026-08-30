import { useEffect, useMemo, useRef, useState } from "react";
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
  type BaseComponents,
  type MetricBreakdown,
  type NullableNumber,
  type RankRow,
  type ResultDocument,
  type ThemeReviewRow,
  type TacticalComponents,
  type TacticalRow,
} from "./lib/dashboard";

type View = "dashboard" | "detail";
type NavTarget = "home" | "tactical" | "base" | "history";
type IconName = "home" | "tactical" | "base" | "history" | "arrow" | "search";

const numberClass = "tabular-nums";
const navItems: Array<{ target: NavTarget; label: string; icon: IconName }> = [
  { target: "home", label: "ホーム", icon: "home" },
  { target: "tactical", label: "Tactical", icon: "tactical" },
  { target: "base", label: "Base", icon: "base" },
  { target: "history", label: "履歴", icon: "history" },
];

type RegimeComponentKey =
  | "nasdaq100_trend"
  | "sp500_trend"
  | "market_breadth"
  | "strategy_leadership"
  | "volatility_regime";
type RegimeComponentKind = "trend" | "breadth" | "leadership" | "volatility";

const regimeComponentDefinitions: Record<RegimeComponentKey, {
  label: string;
  weight: string;
  kind: RegimeComponentKind;
  basis: string;
  scoring: string[];
}> = {
  nasdaq100_trend: {
    label: "NASDAQ100トレンド",
    weight: "20%",
    kind: "trend",
    basis: "NASDAQ100指数の価格と移動平均の位置関係を確認します。",
    scoring: ["価格 > 50DMA：35点", "50DMA > 200DMA：40点", "50DMAの20営業日傾き > 0：25点"],
  },
  sp500_trend: {
    label: "S&P500トレンド",
    weight: "15%",
    kind: "trend",
    basis: "S&P500指数の価格と移動平均の位置関係を確認します。",
    scoring: ["価格 > 50DMA：35点", "50DMA > 200DMA：40点", "50DMAの20営業日傾き > 0：25点"],
  },
  market_breadth: {
    label: "市場の広がり",
    weight: "25%",
    kind: "breadth",
    basis: "各Universeで50DMAを上回る構成銘柄の比率を均等平均します。",
    scoring: ["S&P500：1/3", "NASDAQ100：1/3", "NEXT100：1/3"],
  },
  strategy_leadership: {
    label: "戦略リーダーシップ",
    weight: "20%",
    kind: "leadership",
    basis: "Neutral Base上位20%の20Dリターン中央値をS&P500と比較します。",
    scoring: ["超過リターン +5%以上：100点", "+2%：80点 / 0%：60点", "-3%：30点 / -8%以下：0点（中間は線形補間）"],
  },
  volatility_regime: {
    label: "ボラティリティ",
    weight: "20%",
    kind: "volatility",
    basis: "NASDAQ100の現在の20D実現ボラティリティを過去中央値と比較します。",
    scoring: ["現在値 ÷ 過去252営業日の中央値", "比率 0.8以下：100点", "1.0：90点 / 1.25：70点 / 1.5：50点 / 1.75：25点 / 2.0：0点"],
  },
};

type HelpContent = {
  id: string;
  description: string;
  points?: string[];
};

const detailHelp = {
  tacticalRank: {
    id: "stock-detail-tactical-rank",
    description: "Regime調整後のTacticalスコアを、計算可能な全Universe内で並べた現在順位です。数字が小さいほど上位です。",
    points: ["同点は既存ルールのAverage Rankで処理", "順位は毎週の計測時点で更新"],
  },
  baseRank: {
    id: "stock-detail-base-rank",
    description: "Momentum・Dollar Volume・Betaから作るNeutral Base Scoreを、全Universe内で並べた現在順位です。",
    points: ["Momentum 45% / Volume 30% / Beta 25%", "TacticalのPenaltyやStage判定は含めない"],
  },
  tacticalScore: {
    id: "stock-detail-tactical-score",
    description: "Market Regimeに応じたMomentum・Volume・Betaの配点から、健全度PenaltyとStage4 Penaltyを差し引いたスコアです。",
    points: ["Risk ON：45 / 30 / 25", "Warning：50 / 35 / 15", "Risk OFF：55 / 35 / 10"],
  },
  baseScore: {
    id: "stock-detail-base-score",
    description: "中期の価格モメンタム、売買代金の拡大、S&P500に対するBetaを固定配点で合成したスコアです。",
    points: ["Momentum 45%", "Dollar Volume Expansion 30%", "Adjusted Beta 25%"],
  },
  health: {
    id: "stock-detail-health",
    description: "短期の相対強度と移動平均から、トレンドの健全性を0〜100点で表します。",
    points: ["20D Relative Strength 30%", "63D RS Drawdown 25%", "50DMA Distance 25%", "50DMA Slope 20%", "50点未満はPenalty、35点未満はNew Buy=false"],
  },
  returns: {
    id: "stock-detail-returns",
    description: "価格系列から算出した期間別リターンです。YTDは年初来、MTDは月初来、Weeklyは直近週の変化を示します。",
  },
  stage: {
    id: "stock-detail-stage",
    description: "価格と50DMA・200DMAの位置関係から見たトレンド局面です。Stage4は長期トレンドが弱い状態を示します。",
    points: ["Stage4：Price < 200DMA かつ 50DMA < 200DMA", "Stage4ではTactical Scoreに15点のPenalty", "Stage4銘柄はNew Buy=false"],
  },
  newBuy: {
    id: "stock-detail-new-buy",
    description: "新規採用候補として扱えるかを示すフラグです。ランキング順位だけでなく、健全度とStage4判定を反映します。",
    points: ["健全度35未満はfalse", "Stage4はfalse", "falseでも既存保有やランキング結果は消えない"],
  },
  holdingStatus: {
    id: "stock-detail-holding-status",
    description: "現在のPortfolio内での状態です。ランキング順位と前週Portfolioをもとに、Entry・Hold・Rotationなどを表示します。",
  },
  momentum: {
    id: "stock-detail-momentum",
    description: "Adjusted priceを使った12-1M Momentumです。直近21営業日を除外し、12カ月前から1カ月前までの中期的な価格の強さを測ります。",
    points: ["直近21営業日はLook-aheadを避けるため除外", "全Universe内でPercentile Score化", "Base Scoreへの配点：45%"],
  },
  volumeExpansion: {
    id: "stock-detail-volume-expansion",
    description: "Raw Close × Raw Volumeで求めたDollar Volumeの拡大率です。直近63営業日の平均を、その前189営業日の平均と比較します。",
    points: ["1.0より大きいほど売買代金が拡大", "全Universe内でPercentile Score化", "Base Scoreへの配点：30%"],
  },
  beta: {
    id: "stock-detail-beta",
    description: "週次リターンを使い、S&P500に対する値動きの連動度を推定したAdjusted Betaです。",
    points: ["60カ月以上：24M Beta 60% + 60M Beta 40%", "12〜23カ月：中立の50点", "利用可能期間に応じてBetaを1方向へShrink", "Base Scoreへの配点：25%"],
  },
  relative20d: {
    id: "stock-detail-relative-20d",
    description: "銘柄の20営業日リターンをS&P500の20営業日リターンと比較した短期相対強度です。",
    points: ["全Universe内でPercentile Score化", "順位が小さいほど短期の相対強度が高い", "Healthへの配点：30%"],
  },
  rsDrawdown: {
    id: "stock-detail-rs-drawdown",
    description: "RS（銘柄のAdjusted price ÷ S&P500のAdjusted price）が、過去63営業日の最高値からどれだけ下がっているかを示します。",
    points: ["0%に近いほどRSが高値圏", "下落幅が大きいほどScoreは低下", "Healthへの配点：25%"],
  },
  dma50Distance: {
    id: "stock-detail-dma50-distance",
    description: "現在価格が50DMAからどれだけ離れているかを示します。プラスは50DMAより上、マイナスは下です。",
    points: ["Price ÷ 50DMA − 1で計算", "上方乖離が大きいほどScoreは高い", "Healthへの配点：25%"],
  },
  dma50Slope: {
    id: "stock-detail-dma50-slope",
    description: "現在の50DMAを20営業日前の50DMAと比較した傾きです。移動平均そのものが上向きかを確認します。",
    points: ["現在50DMA ÷ 20営業日前50DMA − 1で計算", "プラスは上向き、マイナスは下向き", "Healthへの配点：20%"],
  },
  primaryTheme: {
    id: "stock-detail-primary-theme",
    description: "企業の主な製品・サービスを優先し、無料のCompany Profile情報からTheme Master内の主テーマを自動判定した結果です。",
    points: ["Product / Service → Industry → Business description → Sectorの順で判定", "計測日ごとのTheme Snapshotを使用", "分類不能時はOther"],
  },
  confidence: {
    id: "stock-detail-theme-confidence",
    description: "主テーマの判定材料と、1位Themeと2位Themeの差から見た分類の確からしさです。",
    points: ["HIGH：1位が明確", "MEDIUM：1位優勢だが差が小さい", "LOW：材料が少ない、または候補が拮抗"],
  },
  themeScore: {
    id: "stock-detail-theme-score",
    description: "Themeごとのキーワード・Sector・Industryの一致度を0〜100点にした値です。ランキングスコアや売買条件には使用しません。",
  },
  secondTheme: {
    id: "stock-detail-second-theme",
    description: "主テーマに次いでテーマスコアが高かった候補です。判定の近さを確認するために表示しています。",
  },
} satisfies Record<string, HelpContent>;

const componentHelp = {
  momentum: detailHelp.momentum,
  volumeExpansion: detailHelp.volumeExpansion,
  beta: detailHelp.beta,
  relative20d: detailHelp.relative20d,
  rsDrawdown: detailHelp.rsDrawdown,
  dma50Distance: detailHelp.dma50Distance,
  dma50Slope: detailHelp.dma50Slope,
} satisfies Record<string, HelpContent>;

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

function numericField(row: RankRow | undefined, key: string): number | null {
  const value = row?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metricFromRow(
  row: RankRow | undefined,
  rawKey: string,
  scoreKey: string,
  rankKey: string,
  previousRankKey?: string,
  rankChangeKey?: string,
): MetricBreakdown {
  return {
    raw: numericField(row, rawKey),
    score: numericField(row, scoreKey),
    rank: numericField(row, rankKey),
    previous_rank: previousRankKey ? numericField(row, previousRankKey) : null,
    rank_change: rankChangeKey ? numericField(row, rankChangeKey) : null,
  };
}

function componentRankChange(metric: MetricBreakdown): number | null {
  const explicit = numberOrNull(metric.rank_change);
  if (explicit !== null) return explicit;
  const previous = numberOrNull(metric.previous_rank);
  const current = numberOrNull(metric.rank);
  if (previous === null || current === null) return null;
  return previous - current;
}

function componentChangeLabel(metric: MetricBreakdown): string {
  if (numberOrNull(metric.previous_rank) === null || numberOrNull(metric.rank) === null) return "—";
  const change = componentRankChange(metric);
  if (change === null || change === 0) return "→";
  return change > 0 ? `↑ ${formatRank(change)}` : `↓ ${formatRank(Math.abs(change))}`;
}

function componentChangeTone(metric: MetricBreakdown): string {
  const change = componentRankChange(metric);
  if (change === null || change === 0) return "return-neutral";
  return change > 0 ? "return-positive" : "return-negative";
}

function componentStrength(score: NullableNumber): string {
  const value = numberOrNull(score);
  if (value === null) return "判定不可";
  if (value >= 85) return "非常に強い";
  if (value >= 70) return "強い";
  if (value >= 50) return "中立";
  if (value >= 35) return "弱い";
  return "非常に弱い";
}

function componentStrengthTone(score: NullableNumber): string {
  const value = numberOrNull(score);
  if (value === null) return "tone-neutral";
  if (value >= 70) return "tone-positive";
  if (value >= 50) return "tone-accent";
  if (value >= 35) return "tone-warning";
  return "tone-negative";
}

function rankWithUniverse(rank: NullableNumber, universeCount: number): string {
  const formatted = rankLabel(rank);
  return formatted === "—" ? "—" : `${formatted} / ${universeCount.toLocaleString("ja-JP")}`;
}

function recordScore(record: unknown, key: string): number | null {
  if (!record || typeof record !== "object") return null;
  const value = (record as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function recordObject(record: unknown, key: string): Record<string, unknown> {
  if (!record || typeof record !== "object") return {};
  const value = (record as Record<string, unknown>)[key];
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function formatRegimeNumber(value: unknown, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "—";
}

function formatSignedRegimeNumber(value: unknown, digits = 1): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function formatRegimePercent(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function regimeCondition(value: unknown): { label: string; tone: string } {
  if (value === true) return { label: "✓ 該当", tone: "is-true" };
  if (value === false) return { label: "— 非該当", tone: "is-false" };
  return { label: "— 判定不可", tone: "is-unknown" };
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, string> = {
    home: "M3 10.5 12 3l9 7.5M5.5 9v10h13V9M9 19v-5h6v5",
    tactical: "M4 18V8m5 10V4m5 14v-7m5 7V6",
    base: "M4 5h16v14H4zM8 9h8M8 13h5M8 17h3",
    history: "M4 12a8 8 0 1 0 2.35-5.65M4 5v4h4M12 7v5l3 2",
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
            aria-current={activeNav === item.target ? "page" : undefined}
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
        <button key={item.target} className={`mobile-nav-item ${activeNav === item.target ? "is-active" : ""}`} aria-current={activeNav === item.target ? "page" : undefined} onClick={() => onNavigate(item.target)}>
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
  const regimeRecord = result.marketRegime as Record<string, unknown>;
  const [openRegimeComponent, setOpenRegimeComponent] = useState<RegimeComponentKey | null>(null);
  useEffect(() => {
    const handleOutsidePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest(".regime-component")) return;
      setOpenRegimeComponent(null);
    };

    document.addEventListener("pointerdown", handleOutsidePointerDown);
    return () => document.removeEventListener("pointerdown", handleOutsidePointerDown);
  }, []);
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
    <main className="page-container dashboard-page" id="home">
      <section className="intro-panel dashboard-hero">
        <div className="intro-copy">
          <div className="hero-kicker-row">
            <p className="eyebrow">US EQUITY SIGNALS / WEEKLY EDITION</p>
            <span className="hero-live"><span className="hero-live-dot" />更新済み</span>
          </div>
          <h1>いま強い銘柄を、<br /><span>毎週見つける。</span></h1>
          <p>市場レジームと相対強度を組み合わせ、現在の市場で相対的に強い銘柄を確認します。</p>
          <div className="hero-methods" aria-label="ランキングの見方">
            <article className="hero-method">
              <div className="hero-method-heading"><span>BASE</span><strong>中立スコア</strong></div>
              <p>Momentum 45%・Volume 30%・Beta 25%で、中期的な強さを測ります。</p>
            </article>
            <article className="hero-method">
              <div className="hero-method-heading"><span>TACTICAL</span><strong>週次シグナル</strong></div>
              <p>Baseを市場レジームで調整し、HealthとStage4を反映した最終順位です。</p>
            </article>
          </div>
          <div className="hero-meta">
            <div><span>最終更新</span><strong className={numberClass}>{formatDate(result.asOf)}</strong></div>
            <div><span>対象銘柄</span><strong className={numberClass}>{result.dataHealth.universe_count.toLocaleString("ja-JP")}</strong></div>
            <div><span>データ状態</span><strong>{formatStatus(result.dataHealth.status)}</strong></div>
          </div>
        </div>
        <div className="dashboard-hero-side">
          <div className="hero-signal-mark" aria-hidden="true">
            <span className="hero-signal-ring hero-signal-ring-outer" />
            <span className="hero-signal-ring hero-signal-ring-inner" />
            <strong>UT</strong>
            <small>SIGNAL<br />ENGINE</small>
          </div>
          <div className="intro-actions">
            <button className="button button-primary" onClick={() => onNavigate("tactical")}>Tacticalを見る <Icon name="arrow" size={16} /></button>
            <button className="button button-secondary" onClick={() => onNavigate("base")}>Baseを見る</button>
          </div>
        </div>
      </section>

      <section className="regime-panel panel panel-highlight dashboard-regime" aria-labelledby="regime-title">
        <div className="dashboard-section-tag"><span>01</span><span>MARKET STATUS</span><span className="dashboard-section-line" /></div>
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
            <span className="regime-score-method">5指標を重み付けして算出。各項目をタップまたはホバーすると詳細を表示</span>
          </div>
          <div className="regime-components">
            {(Object.keys(regimeComponentDefinitions) as RegimeComponentKey[]).map((key) => {
              const definition = regimeComponentDefinitions[key];
              return (
                <RegimeComponent
                  key={key}
                  id={key}
                  label={definition.label}
                  value={recordScore(regimeRecord.component_scores, key)}
                  weight={definition.weight}
                  kind={definition.kind}
                  basis={definition.basis}
                  scoring={definition.scoring}
                  details={recordObject(regimeRecord, key)}
                  isOpen={openRegimeComponent === key}
                  onToggle={() => setOpenRegimeComponent((openKey) => openKey === key ? null : key)}
                />
              );
            })}
          </div>
        </div>
      </section>

      <Top10Comparison result={result} onSelectTicker={onSelectTicker} />

      <section className="summary-grid dashboard-metrics" aria-label="サマリー">
        <MetricCard index="02" label="データ状態" value={formatStatus(result.dataHealth.status)} detail={`${result.dataHealth.missing_tickers.length}銘柄を確認中`} tone={toneForStatus(result.dataHealth.status)} description="市場データの取得状況です。必要なTickerの欠損や履歴不足が1銘柄でもある場合は、不完全として扱います。" />
        <MetricCard index="03" label="採用銘柄" value={`${holdings.length} / 10`} detail={formatStatus(result.portfolioStatus)} tone={toneForStatus(result.portfolioStatus)} description="Portfolio Builderが、Tactical順位・New Buy・Stage4・Theme Constraintを確認して採用した銘柄数です。目標は10銘柄、各10%です。" />
        <MetricCard index="04" label="今週の変動" value={`${rotationChanged} IN / OUT`} detail={`${result.rotation.hold.length} HOLD`} tone="tone-neutral" description="前週Portfolioとの比較です。INは新規採用、OUTは入替対象、HOLDは継続候補を表します。" />
        <MetricCard index="05" label="対象銘柄" value={String(result.dataHealth.universe_count)} detail={`Tactical有効 ${result.dataHealth.tactical_eligible_count}`} tone="tone-accent" description="S&P500・NASDAQ100・NEXT100を重複除去して統合したUniverseの銘柄数です。Tactical有効数は必要な計算データが揃った銘柄数です。" />
      </section>

      <section className="content-grid dashboard-content-grid" id="portfolio">
        <div className="panel panel-wide">
          <SectionHeading title="採用10銘柄" kicker="採用銘柄 / 10%均等配分" />
          {holdings.length > 0 ? (
            <div className="portfolio-grid">
              {holdings.map((holding, index) => {
                const tactical = tacticalByTicker[holding.ticker];
                return (
                  <button className="holding-card" key={holding.ticker} onClick={() => onSelectTicker(holding.ticker)} aria-label={`${holding.ticker}の詳細を開く`}>
                    <div className="holding-card-head">
                      <span className="holding-index">{String(index + 1).padStart(2, "0")}</span>
                      <div className="holding-topline">
                        <span className="ticker-label">{holding.ticker}</span>
                        <span className={`mini-pill ${toneForStatus(holding.status ?? "")}`}>{formatStatus(holding.status)}</span>
                      </div>
                    </div>
                    <span className="holding-theme">{holding.theme ?? "テーマ未設定"}</span>
                    <div className="holding-ranks">
                      <span><small>Tactical</small><strong className="rank-emphasis">{rankLabel(holding.tactical_rank)}</strong></span>
                      <span><small>Base</small><strong>{rankLabel(holding.base_rank)}</strong></span>
                      <span><small>健全度</small><strong className={numberClass}>{formatScore(tactical?.health)}</strong></span>
                    </div>
                    <span className="holding-health-track"><span style={{ width: `${Math.max(0, Math.min(100, numberOrNull(tactical?.health) ?? 0))}%` }} /></span>
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

        <div className="panel dashboard-rotation" id="rotation">
          <SectionHeading title="今週のローテーション" kicker="週次ローテーション / 前回比較" />
          <RotationPanel result={result} onSelectTicker={onSelectTicker} />
        </div>
      </section>

      <ThemeStatusPanel snapshot={result.themeSnapshot ?? []} changes={result.themeChanges ?? []} onSelectTicker={onSelectTicker} />

      <section className="panel tactical-ranking-panel" id="tactical">
        <div className="ranking-panel-bar"><span>06</span><span>Tactical / 週次シグナル</span><span className="dashboard-section-line" /><span className="ranking-panel-state">初期：上位10</span></div>
        <SectionHeading title="Tacticalランキング" kicker={`${topTactical.length}銘柄が計算対象 / 並べ替え・検索`} />
        <TacticalTable result={result} onSelectTicker={onSelectTicker} />
      </section>

      <section className="panel base-ranking-panel" id="base">
        <div className="ranking-panel-bar"><span>07</span><span>Base / 中立スコア</span><span className="dashboard-section-line" /><span className="ranking-panel-state">初期：上位10</span></div>
        <SectionHeading title="Baseランキング" kicker="上位10銘柄 / 11位以下は展開" />
        <BaseTable rows={result.baseRanking} onSelectTicker={onSelectTicker} />
      </section>

      <HistoryPanel result={result} onSelectTicker={onSelectTicker} />
    </main>
  );
}

function Top10Comparison({ result, onSelectTicker }: { result: ResultDocument; onSelectTicker: (ticker: string) => void }) {
  const themeByTicker = useMemo(() => {
    const map: Record<string, string> = {};
    (result.themeSnapshot ?? []).forEach((row) => { map[row.ticker] = row.primary_theme; });
    result.themeReview.forEach((row) => { if (row.current_theme) map[row.ticker] = row.current_theme; });
    result.portfolio.forEach((row) => { if (row.theme) map[row.ticker] = row.theme; });
    return map;
  }, [result.portfolio, result.themeReview, result.themeSnapshot]);
  const tacticalTop10 = useMemo(
    () => [...result.tacticalRanking]
      .filter((row) => numberOrNull(row.tactical_rank) !== null)
      .sort((a, b) => (numberOrNull(a.tactical_rank) ?? Number.POSITIVE_INFINITY) - (numberOrNull(b.tactical_rank) ?? Number.POSITIVE_INFINITY))
      .slice(0, 10),
    [result.tacticalRanking],
  );
  const baseTop10 = useMemo(
    () => [...result.baseRanking]
      .filter((row) => numberOrNull(row.base_rank) !== null)
      .sort((a, b) => (numberOrNull(a.base_rank) ?? Number.POSITIVE_INFINITY) - (numberOrNull(b.base_rank) ?? Number.POSITIVE_INFINITY))
      .slice(0, 10),
    [result.baseRanking],
  );
  const tacticalRankByTicker = useMemo(
    () => Object.fromEntries(result.tacticalRanking.map((row) => [row.ticker, numberOrNull(row.tactical_rank)])),
    [result.tacticalRanking],
  );
  const baseRankByTicker = useMemo(
    () => Object.fromEntries(result.baseRanking.map((row) => [row.ticker, numberOrNull(row.base_rank)])),
    [result.baseRanking],
  );
  const sharedTickers = useMemo(
    () => new Set(tacticalTop10.map((row) => row.ticker).filter((ticker) => baseTop10.some((row) => row.ticker === ticker))),
    [baseTop10, tacticalTop10],
  );

  return (
    <section className="panel top10-compare-panel" id="top10" aria-labelledby="top10-title">
      <div className="dashboard-section-tag"><span>02</span><span>RANKING SNAPSHOT</span><span className="dashboard-section-line" /></div>
      <div className="panel-heading top10-compare-heading">
        <div><p className="eyebrow">現在の上位銘柄</p><h2 id="top10-title">BaseとTacticalを比較</h2></div>
        <span className="top10-compare-note">共通銘柄は控えめに強調</span>
      </div>
      <div className="top10-compare-intro">
        <div className="top10-compare-intro-copy"><span>ONE MARKET / TWO LENSES</span><p>中期のBaseと週次のTactical。2つの視点で、いま強い銘柄の重なりと違いを確認します。</p></div>
        <div className="top10-compare-stats"><span><strong>{sharedTickers.size}</strong><small>共通銘柄</small></span><span><strong>{tacticalTop10.length}</strong><small>Tactical</small></span><span><strong>{baseTop10.length}</strong><small>Base</small></span></div>
      </div>
      <div className="top10-compare-grid">
        <Top10List
          title="Tactical Top 10"
          subtitle="週次シグナル / Market Regime・健全度を反映"
          scoreLabel="Tactical"
          counterpartLabel="Base"
          rows={tacticalTop10}
          rankKey="tactical_rank"
          scoreKey="tactical_score"
          counterpartRanks={baseRankByTicker}
          themeByTicker={themeByTicker}
          sharedTickers={sharedTickers}
          onSelectTicker={onSelectTicker}
        />
        <Top10List
          title="Base Top 10"
          subtitle="中立スコア / Momentum・Volume・Beta"
          scoreLabel="Base"
          counterpartLabel="Tactical"
          rows={baseTop10}
          rankKey="base_rank"
          scoreKey="base_score"
          counterpartRanks={tacticalRankByTicker}
          themeByTicker={themeByTicker}
          sharedTickers={sharedTickers}
          onSelectTicker={onSelectTicker}
        />
      </div>
    </section>
  );
}

function Top10List({
  title,
  subtitle,
  scoreLabel,
  counterpartLabel,
  rows,
  rankKey,
  scoreKey,
  counterpartRanks,
  themeByTicker,
  sharedTickers,
  onSelectTicker,
}: {
  title: string;
  subtitle: string;
  scoreLabel: string;
  counterpartLabel: string;
  rows: RankRow[];
  rankKey: "base_rank" | "tactical_rank";
  scoreKey: "base_score" | "tactical_score";
  counterpartRanks: Record<string, number | null>;
  themeByTicker: Record<string, string>;
  sharedTickers: Set<string>;
  onSelectTicker: (ticker: string) => void;
}) {
  return (
    <article className={`top10-list ${scoreLabel === "Tactical" ? "top10-list-tactical" : "top10-list-base"}`}>
      <div className="top10-list-heading"><div className="top10-list-title-row"><span className="top10-list-mark">{scoreLabel === "Tactical" ? "T" : "B"}</span><div><span className="top10-list-eyebrow">{scoreLabel === "Tactical" ? "WEEKLY SIGNAL" : "NEUTRAL BASE"}</span><h3>{title}</h3><p>{subtitle}</p></div></div><span className="top10-list-count">{rows.length}銘柄</span></div>
      <div className="top10-list-body">
        {rows.length > 0 ? rows.map((row, index) => {
          const rank = numberOrNull(row[rankKey] as number | null);
          const score = numberOrNull(row[scoreKey] as number | null);
          const counterpartRank = counterpartRanks[row.ticker];
          const isShared = sharedTickers.has(row.ticker);
          return (
            <button className={`top10-row ${index < 3 ? "is-podium" : ""} ${isShared ? "is-shared" : ""}`} key={row.ticker} onClick={() => onSelectTicker(row.ticker)} aria-label={`${row.ticker}の詳細を開く`}>
              <span className="top10-row-rank">{String(index + 1).padStart(2, "0")}</span>
              <span className="top10-row-ticker"><strong>{row.ticker}</strong>{isShared && <small>共通</small>}</span>
              <span className="top10-row-score"><small>{scoreLabel}</small><strong className={numberClass}>{formatScore(score)}</strong><i className="top10-score-bar"><b style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} /></i></span>
              <span className="top10-row-counterpart"><small>{counterpartLabel}</small><strong>{rankLabel(counterpartRank)}</strong></span>
              <span className="top10-row-theme">{themeByTicker[row.ticker] ?? "テーマ未設定"}</span>
              <span className="top10-row-rank-value">現在 {rankLabel(rank)}</span>
            </button>
          );
        }) : <div className="top10-empty">表示できる銘柄がありません</div>}
      </div>
    </article>
  );
}

function RegimeComponent({
  id,
  label,
  value,
  weight,
  kind,
  basis,
  scoring,
  details,
  isOpen,
  onToggle,
}: {
  id: RegimeComponentKey;
  label: string;
  value: number | null;
  weight: string;
  kind: RegimeComponentKind;
  basis: string;
  scoring: string[];
  details: Record<string, unknown>;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const tooltipId = `regime-help-${id}`;

  return (
    <div className={`regime-component ${isOpen ? "is-open" : ""}`}>
      <button
        type="button"
        className="regime-component-trigger"
        aria-controls={tooltipId}
        aria-expanded={isOpen}
        onClick={onToggle}
      >
        <span>{label}</span>
        <span className="regime-info-mark" aria-hidden="true">i</span>
      </button>
      <strong className={numberClass}>{formatScore(value)}</strong>
      <div className="score-track"><span style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} /></div>
      <div id={tooltipId} className="regime-tooltip" role="tooltip">
        <div className="regime-tooltip-heading">
          <strong>算出方法</strong>
          <span>配点 {weight}</span>
        </div>
        <p>{basis}</p>
        <ul>
          {scoring.map((rule) => <li key={rule}>{rule}</li>)}
        </ul>
        <RegimeEvidence kind={kind} details={details} />
      </div>
    </div>
  );
}

function RegimeEvidence({ kind, details }: { kind: RegimeComponentKind; details: Record<string, unknown> }) {
  if (kind === "trend") {
    const priceAbove = regimeCondition(details.price_above_50dma);
    const dmaAbove = regimeCondition(details.dma50_above_200dma);
    const slopePositive = regimeCondition(details.slope_positive);
    return (
      <div className="regime-evidence">
        <div><span>価格 / 50DMA</span><strong>{formatRegimeNumber(details.price)} / {formatRegimeNumber(details.dma50)}</strong><em className={priceAbove.tone}>{priceAbove.label}</em></div>
        <div><span>50DMA / 200DMA</span><strong>{formatRegimeNumber(details.dma50)} / {formatRegimeNumber(details.dma200)}</strong><em className={dmaAbove.tone}>{dmaAbove.label}</em></div>
        <div><span>50DMA 20D傾き</span><strong>{formatSignedRegimeNumber(details.dma50_slope_20d)}</strong><em className={slopePositive.tone}>{slopePositive.label}</em></div>
      </div>
    );
  }

  if (kind === "breadth") {
    const ratios = details.ratios && typeof details.ratios === "object" ? details.ratios as Record<string, unknown> : {};
    const memberCounts = details.member_counts && typeof details.member_counts === "object" ? details.member_counts as Record<string, unknown> : {};
    return (
      <div className="regime-evidence">
        {[["S&P500", "sp500"], ["NASDAQ100", "nasdaq100"], ["NEXT100", "next100"]].map(([label, key]) => (
          <div key={key}><span>{label} / 50DMA上</span><strong>{formatRegimePercent(ratios[key])}</strong><em>{formatRegimeNumber(memberCounts[key], 0)}銘柄</em></div>
        ))}
      </div>
    );
  }

  if (kind === "leadership") {
    const excess = typeof details.excess_20d_return === "number" && Number.isFinite(details.excess_20d_return)
      ? details.excess_20d_return
      : null;
    return (
      <div className="regime-evidence">
        <div><span>Neutral Base上位</span><strong>{formatRegimeNumber(details.leader_count, 0)}銘柄</strong><em>中央値</em></div>
        <div><span>上位20%の20D</span><strong>{formatRegimePercent(details.leaders_median_20d_return)}</strong><em>リターン</em></div>
        <div><span>S&P500 20D</span><strong>{formatRegimePercent(details.sp500_20d_return)}</strong><em>比較対象</em></div>
        <div><span>超過リターン</span><strong>{excess === null ? "—" : `${formatSignedRegimeNumber(excess * 100)}%`}</strong><em>スコア入力</em></div>
      </div>
    );
  }

  return (
    <div className="regime-evidence">
      <div><span>現在20D実現Vol</span><strong>{formatRegimePercent(details.current_20d_realized_vol)}</strong><em>年率換算</em></div>
      <div><span>過去中央値</span><strong>{formatRegimePercent(details.historical_median_20d_realized_vol)}</strong><em>252営業日</em></div>
      <div><span>現在 ÷ 中央値</span><strong>{formatRegimeNumber(details.ratio, 2)}</strong><em>低いほど高得点</em></div>
    </div>
  );
}

function InfoPopover({
  id,
  title,
  description,
  points = [],
  label,
  className = "",
}: {
  id: string;
  title: string;
  description: string;
  points?: string[];
  label?: string;
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = `${id}-info`;

  useEffect(() => {
    const handleOutsidePointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && rootRef.current?.contains(event.target)) return;
      setIsOpen(false);
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };

    document.addEventListener("pointerdown", handleOutsidePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handleOutsidePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  return (
    <div ref={rootRef} className={`info-popover ${isOpen ? "is-open" : ""} ${className}`}>
      <button
        type="button"
        className={`info-popover-trigger ${label ? "has-label" : "icon-only"}`}
        aria-controls={panelId}
        aria-expanded={isOpen}
        aria-label={`${title}の説明を表示`}
        onClick={() => setIsOpen((open) => !open)}
      >
        {label && <span>{label}</span>}
        <span className="info-popover-mark" aria-hidden="true">i</span>
      </button>
      <div id={panelId} className="info-popover-panel" role="tooltip">
        <div className="info-popover-heading"><strong>{title}</strong><span>説明</span></div>
        <p>{description}</p>
        {points.length > 0 && <ul>{points.map((point) => <li key={point}>{point}</li>)}</ul>}
      </div>
    </div>
  );
}

function MetricCard({ index, label, value, detail, tone, description }: { index: string; label: string; value: string; detail: string; tone: string; description: string }) {
  return (
    <article className="metric-card">
      <div className="metric-card-topline"><span className="metric-index">{index}</span><InfoPopover id={`summary-${index}`} title={label} description={description} label={label} className="metric-card-info" /></div>
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
        <strong>採用銘柄を確認中です</strong>
        <p>{rows.length > 0 ? `Tactical上位30銘柄のTheme判定を確認中です。` : "採用候補を確定できるデータがまだありません。"} 次回のバッチで再計算されます。</p>
        <div className="review-tickers">
          {rows.slice(0, 10).map((row) => <span key={row.ticker}>{row.ticker}</span>)}
          {rows.length > 10 && <span>+{rows.length - 10}</span>}
        </div>
      </div>
    </div>
  );
}

function ThemeStatusPanel({
  snapshot,
  changes,
  onSelectTicker,
}: {
  snapshot: NonNullable<ResultDocument["themeSnapshot"]>;
  changes: NonNullable<ResultDocument["themeChanges"]>;
  onSelectTicker: (ticker: string) => void;
}) {
  return (
    <section className="panel theme-review-panel" id="theme-review">
      <SectionHeading title="テーマ自動判定" kicker={`Tactical上位${Math.min(30, snapshot.length)}銘柄を含む全Universe`} />
      <div className="theme-auto-summary">
        <div><strong>{snapshot.length}銘柄</strong><span>主テーマを自動分類済み</span></div>
        <div><strong>{changes.length}件</strong><span>今回のテーマ変更</span></div>
      </div>
      {changes.length > 0 ? (
        <div className="theme-change-list">
          {changes.map((change) => (
            <button className="theme-change-row" key={`${change.ticker}-${change.as_of}`} onClick={() => onSelectTicker(change.ticker)}>
              <span className="theme-review-main"><strong>{change.ticker}</strong><small>{formatDate(change.as_of)}</small></span>
              <span className="theme-change-path"><span>{change.previous_theme}</span><b>→</b><span>{change.new_theme}</span></span>
              <span className="mini-pill tone-accent">テーマ変更</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty-state compact-empty"><span className="empty-mark">✓</span><strong>今回のテーマ変更はありません</strong><small>全銘柄を主テーマへ自動分類済みです</small></div>
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

function RankingViewControl({ showAll, totalCount, onToggle }: { showAll: boolean; totalCount: number; onToggle: () => void }) {
  if (totalCount <= 10) return null;
  return (
    <div className="ranking-view-control">
      <span>{showAll ? `全${totalCount.toLocaleString("ja-JP")}件` : `上位${Math.min(10, totalCount)}件`}</span>
      <button type="button" className="ranking-view-button" onClick={onToggle} aria-expanded={showAll}>
        {showAll ? "上位10件に戻す" : "11位以下を表示"}
      </button>
    </div>
  );
}

function BaseTable({ rows, onSelectTicker }: { rows: RankRow[]; onSelectTicker: (ticker: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const rankedRows = useMemo(
    () => [...rows].sort((a, b) => (numberOrNull(a.base_rank) ?? Number.POSITIVE_INFINITY) - (numberOrNull(b.base_rank) ?? Number.POSITIVE_INFINITY)),
    [rows],
  );
  const visibleRows = useMemo(() => showAll ? rankedRows : rankedRows.slice(0, 10), [rankedRows, showAll]);

  return (
    <>
      <RankingViewControl showAll={showAll} totalCount={rankedRows.length} onToggle={() => setShowAll((current) => !current)} />
      <div className="table-scroll">
        <table key={showAll ? "base-all" : "base-top10"} className="data-table compact-table base-table" aria-label="Baseランキング">
          <thead><tr><th>順位</th><th className="ticker-header">Ticker</th><th>Base</th><th>Momentum</th><th>売買代金</th><th>Beta</th></tr></thead>
          <tbody>
            {visibleRows.map((row) => {
              const rank = numberOrNull(row.base_rank);
              const rankBand = rank !== null && rank <= 5 ? "is-top-five" : rank !== null && rank <= 10 ? "is-top-ten" : "";
              const score = numberOrNull(row.base_score);
              return (
              <tr key={row.ticker} className={`base-row ${rankBand}`}>
                <td className={numberClass}>{formatRank(row.base_rank)}</td>
                <td className="ticker-cell"><button className="ticker-button" onClick={() => onSelectTicker(row.ticker)}>{row.ticker}</button></td>
                <td className={`${numberClass} base-score-cell`}><span>{formatScore(row.base_score)}</span><span className="table-score-meter"><span style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} /></span></td>
                <td className={numberClass}>{formatScore(row.momentum_score)}</td>
                <td className={numberClass}>{formatScore(row.volume_score)}</td>
                <td className={numberClass}>{formatScore(row.beta_score)}</td>
              </tr>
              );
            })}
            {visibleRows.length === 0 && <tr><td className="table-empty" colSpan={6}>表示できるTickerがありません</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function TacticalTable({ result, onSelectTicker }: { result: ResultDocument; onSelectTicker: (ticker: string) => void }) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "tactical_rank", desc: false }]);
  const [showAll, setShowAll] = useState(false);
  const themeByTicker = useMemo(() => {
    const map: Record<string, string> = {};
    (result.themeSnapshot ?? []).forEach((row) => { map[row.ticker] = row.primary_theme; });
    result.themeReview.forEach((row) => { if (row.current_theme) map[row.ticker] = row.current_theme; });
    result.portfolio.forEach((row) => { if (row.theme) map[row.ticker] = row.theme; });
    return map;
  }, [result.portfolio, result.themeReview, result.themeSnapshot]);
  const rows = useMemo<TacticalRow[]>(() => result.tacticalRanking.map((row) => ({
    ...row,
    theme: row.primary_theme ?? themeByTicker[row.ticker] ?? null,
    status: getTacticalStatus(row),
  })), [result.tacticalRanking, themeByTicker]);
  const rankedRows = useMemo(
    () => [...rows].sort((a, b) => (numberOrNull(a.tactical_rank) ?? Number.POSITIVE_INFINITY) - (numberOrNull(b.tactical_rank) ?? Number.POSITIVE_INFINITY)),
    [rows],
  );
  const displayedRows = useMemo(() => showAll ? rankedRows : rankedRows.slice(0, 10), [rankedRows, showAll]);
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
    data: displayedRows,
    columns,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const visibleRows = table.getRowModel().rows;
  const displayedCount = displayedRows.length;

  return (
    <>
      <div className="table-toolbar">
        <div className="table-toolbar-leading">
          <span className="toolbar-label">銘柄を絞り込む</span>
          <label className="search-box"><Icon name="search" size={16} /><input value={globalFilter} onChange={(event) => setGlobalFilter(event.target.value)} placeholder="Tickerを検索" aria-label="Tickerを検索" /></label>
        </div>
        <div className="table-toolbar-trailing"><span className="table-count">{visibleRows.length} / {displayedCount} 件</span><RankingViewControl showAll={showAll} totalCount={rankedRows.length} onToggle={() => setShowAll((current) => !current)} /><span className="toolbar-hint">列名をタップして並べ替え</span></div>
      </div>
          <div className="table-scroll">
        <table key={showAll ? "tactical-all" : "tactical-top10"} className="data-table tactical-table" aria-label="Tacticalランキング">
          <thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => {
            const sorted = header.column.getIsSorted();
            const help = header.column.id === "tactical_score"
              ? {
                id: "tactical-score-header",
                title: "Tacticalスコア",
                description: "Market Regimeに応じたMomentum・Volume・BetaのBase配分から、Tactical Healthに基づくPenaltyとStage4 Penaltyを引いた最終スコアです。",
                points: ["Risk ON：45 / 30 / 25", "Warning：50 / 35 / 15", "Risk OFF：55 / 35 / 10", "順番は Momentum / Volume / Beta"],
              }
              : header.column.id === "health"
                ? {
                  id: "health-header",
                  title: "健全度",
                  description: "短期の相対強度とトレンド維持力をまとめた100点満点の健康度です。",
                  points: ["20D Relative Strength：30%", "63D RS Drawdown：25%", "50DMA Distance：25%", "50DMA Slope：20%", "50未満はPenalty、35未満はNew Buy=false"],
                }
                : null;
            return (
              <th key={header.id} className={header.column.id === "ticker" ? "ticker-header" : ""} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                <div className="table-header-label">
                  <button className={header.column.getCanSort() ? "sort-button" : "sort-button disabled"} onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}>{flexRender(header.column.columnDef.header, header.getContext())}{sorted === "asc" ? " ↑" : sorted === "desc" ? " ↓" : ""}</button>
                  {help && <InfoPopover {...help} className="table-header-help" />}
                </div>
              </th>
            );
          })}</tr>)}</thead>
          <tbody>
            {visibleRows.map((row) => { const rank = numberOrNull(row.original.tactical_rank); const rankBand = rank !== null && rank <= 10 ? "is-entry" : rank !== null && rank <= 15 ? "is-hold" : "is-rotation"; return <tr key={row.id} className={`tactical-row ${rankBand}`}>{row.getVisibleCells().map((cell) => <td key={cell.id} className={cell.column.id === "ticker" ? "ticker-cell" : ""}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>; })}
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
    <section className="panel history-panel" id="history">
      <div className="ranking-panel-bar history-section-bar"><span>08</span><span>HISTORY / WEEKLY MOVEMENT</span><span className="dashboard-section-line" /><span className="ranking-panel-state">{changes.length > 0 ? `${changes.length}件` : "比較待ち"}</span></div>
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

function StockDetail({ result, ticker, onBack }: { result: ResultDocument; ticker: string; onBack: () => void }) {
  const tactical = result.tacticalRanking.find((row) => row.ticker === ticker);
  const base = result.baseRanking.find((row) => row.ticker === ticker);
  const holding = result.portfolio.find((row) => row.ticker === ticker);
  const theme = (result.themeSnapshot ?? []).find((row) => row.ticker === ticker);
  const history = stockRankHistory(ticker, result);
  if (!tactical && !base) return <main className="page-container detail-page"><button className="back-button" onClick={onBack}>← ダッシュボードに戻る</button><div className="panel empty-state"><strong>銘柄が見つかりません</strong><small>現在の結果JSONに該当Tickerがありません</small></div></main>;

  const currentStatus = tactical ? getTacticalStatus(tactical) : "Unranked";
  const baseSummary = tactical?.base ?? base?.base ?? {
    rank: tactical?.base_rank ?? base?.base_rank,
    previous_rank: numericField(tactical, "base_previous_rank"),
    rank_change: numericField(tactical, "base_rank_change"),
    score: tactical?.base_score ?? base?.base_score,
  };
  const tacticalSummary = tactical?.tactical ?? {
    rank: tactical?.tactical_rank,
    previous_rank: numericField(tactical, "tactical_previous_rank"),
    rank_change: numericField(tactical, "tactical_rank_change"),
    score: tactical?.tactical_score,
    health: tactical?.health,
    penalty: tactical?.penalty,
  };
  const baseComponents: BaseComponents = tactical?.base_components ?? base?.base_components ?? {
    momentum: metricFromRow(base ?? tactical, "momentum_raw", "momentum_score", "momentum_rank", "momentum_previous_rank", "momentum_rank_change"),
    volume_expansion: metricFromRow(base ?? tactical, "volume_expansion_raw", "volume_score", "volume_expansion_rank", "volume_expansion_previous_rank", "volume_expansion_rank_change"),
    beta: metricFromRow(base ?? tactical, "beta_raw", "beta_score", "beta_rank", "beta_previous_rank", "beta_rank_change"),
  };
  const tacticalComponents: TacticalComponents = tactical?.tactical_components ?? {
    relative_20d: metricFromRow(tactical, "relative_20d_raw", "relative_20d_score", "relative_20d_rank"),
    rs_drawdown_63d: metricFromRow(tactical, "rs_drawdown_raw", "rs_drawdown_score", "rs_drawdown_rank"),
    dma50_distance: metricFromRow(tactical, "dma50_distance_raw", "dma50_distance_score", "dma50_distance_rank"),
    dma50_slope: metricFromRow(tactical, "dma50_slope_raw", "dma50_slope_score", "dma50_slope_rank"),
  };
  return (
    <main className="page-container detail-page">
      <button className="back-button" onClick={onBack}>← ダッシュボードに戻る</button>
      <section className="detail-hero">
        <div className="detail-hero-copy">
          <p className="eyebrow">銘柄詳細 / {formatDate(result.asOf)}</p>
          <div className="detail-title-row">
            <h1>{ticker}</h1>
            <span className={`status-pill detail-status ${toneForStatus(currentStatus)}`}>{tacticalStatusLabel(currentStatus)}</span>
          </div>
          <div className="detail-theme-line"><span>主テーマ</span><strong>{theme?.primary_theme ?? tactical?.primary_theme ?? holding?.theme ?? "その他"}</strong></div>
          <div className="detail-rank-compare">
            <div><span>Base順位</span><strong>{rankLabel(baseSummary.rank)}</strong></div>
            <div><span>Tactical順位</span><strong className="accent-text">{rankLabel(tacticalSummary.rank)}</strong></div>
          </div>
        </div>
      </section>
      <section className="detail-grid">
        <div className="panel chart-panel detail-panel">
          <div className="detail-panel-bar"><span>順位履歴</span><small>前回と今回のTactical順位</small></div>
          <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><LineChart data={history} margin={{ top: 12, right: 10, left: -20, bottom: 4 }}><CartesianGrid strokeDasharray="3 3" stroke="#263244" /><XAxis dataKey="period" stroke="#718096" tickLine={false} axisLine={false} /><YAxis reversed allowDecimals={false} stroke="#718096" tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: "#151b27", border: "1px solid rgba(255,255,255,.1)", borderRadius: 10 }} labelStyle={{ color: "#f5f7fa" }} /><Line type="monotone" dataKey="tacticalRank" name="Tactical" stroke="#4cc9f0" strokeWidth={2.5} dot={{ r: 4, fill: "#4cc9f0", stroke: "#080b12", strokeWidth: 2 }} connectNulls /></LineChart></ResponsiveContainer></div>
        </div>
        <div className="panel detail-stats detail-panel">
          <SectionHeading title="スナップショット" kicker="現在値" />
          <DetailStat label="Tactical順位" value={rankLabel(tacticalSummary.rank)} accent help={detailHelp.tacticalRank} />
          <DetailStat label="Base順位" value={rankLabel(baseSummary.rank)} help={detailHelp.baseRank} helpAlign="right" />
          <DetailStat label="Tacticalスコア" value={formatScore(tacticalSummary.score)} help={detailHelp.tacticalScore} />
          <DetailStat label="Baseスコア" value={formatScore(baseSummary.score)} help={detailHelp.baseScore} helpAlign="right" />
          <DetailStat label="健全度" value={formatScore(tacticalSummary.health)} help={detailHelp.health} />
          <DetailStat label="YTD / MTD" value={`${formatPercent(tactical?.ytd)} / ${formatPercent(tactical?.mtd)}`} help={detailHelp.returns} helpAlign="right" />
          <DetailStat label="Weekly" value={formatPercent(tactical?.weekly)} help={detailHelp.returns} />
          <DetailStat label="Stage" value={stageLabel(tactical?.stage)} help={detailHelp.stage} helpAlign="right" />
          <DetailStat label="New Buy" value={tactical?.new_buy === undefined ? "—" : tactical.new_buy ? "true" : "false"} help={detailHelp.newBuy} />
          <DetailStat label="採用状態" value={holding ? formatStatus(holding.status) : "未採用"} help={detailHelp.holdingStatus} helpAlign="right" />
        </div>
       </section>
      <BaseComponentsPanel components={baseComponents} universeCount={result.dataHealth.universe_count} />
      <TacticalComponentsPanel components={tacticalComponents} universeCount={result.dataHealth.universe_count} />
      <ThemeDetailStats snapshot={theme} />
     </main>
  );
}

function BaseComponentsPanel({ components, universeCount }: { components: BaseComponents; universeCount: number }) {
  return (
    <section className="panel detail-panel component-panel">
      <div className="detail-panel-bar"><span>Base構成</span><small>Baseスコアの構成要素 / 全Universe順位</small></div>
      <div className="component-grid">
        <ComponentCard label="Momentum" help={componentHelp.momentum} metric={components.momentum} universeCount={universeCount} />
        <ComponentCard label="Dollar Volume拡大" help={componentHelp.volumeExpansion} metric={components.volume_expansion} universeCount={universeCount} />
        <ComponentCard label="Beta" help={componentHelp.beta} metric={components.beta} universeCount={universeCount} />
      </div>
    </section>
  );
}

function TacticalComponentsPanel({ components, universeCount }: { components: TacticalComponents; universeCount: number }) {
  return (
    <section className="panel detail-panel component-panel">
      <div className="detail-panel-bar"><span>Tactical構成</span><small>健全度を構成する4指標 / RawとScore</small></div>
      <div className="component-grid tactical-component-grid">
        <ComponentCard label="20D相対強度" help={componentHelp.relative20d} metric={components.relative_20d} universeCount={universeCount} showRaw rawAsPercent />
        <ComponentCard label="63D RSドローダウン" help={componentHelp.rsDrawdown} metric={components.rs_drawdown_63d} universeCount={universeCount} showRaw rawAsPercent />
        <ComponentCard label="50DMA乖離" help={componentHelp.dma50Distance} metric={components.dma50_distance} universeCount={universeCount} showRaw rawAsPercent />
        <ComponentCard label="50DMA傾き" help={componentHelp.dma50Slope} metric={components.dma50_slope} universeCount={universeCount} showRaw rawAsPercent />
      </div>
    </section>
  );
}

function ComponentCard({ label, help, metric, universeCount, showRaw = false, rawAsPercent = false }: { label: string; help: HelpContent; metric: MetricBreakdown | undefined; universeCount: number; showRaw?: boolean; rawAsPercent?: boolean }) {
  const score = numberOrNull(metric?.score);
  return (
    <article className="component-card">
      <div className="component-card-heading"><div className="component-card-title"><strong>{label}</strong><InfoPopover {...help} title={label} className="component-card-help" /></div><span className={`component-strength ${componentStrengthTone(score)}`}>{componentStrength(score)}</span></div>
      <div className="component-rank-line"><span>順位</span><strong>{rankWithUniverse(metric?.rank, universeCount)}</strong><span className={`component-change ${componentChangeTone(metric ?? {})}`}>{componentChangeLabel(metric ?? {})}</span></div>
      <div className="component-value-line"><span>Score</span><strong className={numberClass}>{formatScore(score)}</strong></div>
      {showRaw && <div className="component-value-line component-raw-line"><span>Raw値</span><strong className={numberClass}>{rawAsPercent ? formatPercent(metric?.raw) : formatScore(metric?.raw)}</strong></div>}
      <div className="component-score-track"><span style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} /></div>
    </article>
  );
}

function ThemeDetailStats({ snapshot }: { snapshot: NonNullable<ResultDocument["themeSnapshot"]>[number] | undefined }) {
  return (
    <section className="panel detail-stats theme-detail-panel detail-panel">
      <SectionHeading title="テーマ判定" kicker="自動分類 / 現在のSnapshot" />
      <DetailStat label="主テーマ" value={snapshot?.primary_theme ?? "その他"} accent help={detailHelp.primaryTheme} />
      <DetailStat label="確信度" value={snapshot?.confidence ?? "LOW"} help={detailHelp.confidence} helpAlign="right" />
      <DetailStat label="テーマスコア" value={formatScore(snapshot?.theme_score)} help={detailHelp.themeScore} />
      <DetailStat label="第2テーマ" value={`${snapshot?.second_theme ?? "その他"} / ${formatScore(snapshot?.second_theme_score)}`} help={detailHelp.secondTheme} helpAlign="right" />
    </section>
  );
}

function DetailStat({ label, value, accent = false, help, helpAlign = "left" }: { label: string; value: string; accent?: boolean; help?: HelpContent; helpAlign?: "left" | "right" }) {
  return <div className={`detail-stat detail-stat-help-${helpAlign}`}><div className="detail-stat-label"><span>{label}</span>{help && <InfoPopover {...help} title={label} className="detail-stat-help" />}</div><strong className={`${accent ? "accent-text" : ""} ${numberClass}`}>{value}</strong></div>;
}

function LoadingState() {
  return <div className="state-screen" role="status" aria-label="ランキング結果を読み込み中"><div className="loading-card"><div className="skeleton skeleton-logo" /><div className="skeleton skeleton-title" /><div className="skeleton skeleton-line" /><div className="skeleton-grid"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div></div><p>ランキング結果を読み込んでいます…</p></div>;
}

function ErrorState() {
  return <div className="state-screen"><div className="error-mark">!</div><h1>データを表示できません</h1><p>ランキング結果の読み込みに失敗しました。</p><p className="empty-copy">データ取得状況を確認してから、もう一度お試しください。</p></div>;
}

export default App;
