export type NullableNumber = number | null | undefined;

export type RankRow = {
  ticker: string;
  base_rank?: NullableNumber;
  base_score?: NullableNumber;
  momentum_score?: NullableNumber;
  volume_score?: NullableNumber;
  beta_score?: NullableNumber;
  [key: string]: unknown;
};

export type TacticalRow = RankRow & {
  tactical_rank?: NullableNumber;
  rank_change?: NullableNumber;
  tactical_score?: NullableNumber;
  health?: NullableNumber;
  stage?: string;
  new_buy?: boolean;
  ytd?: NullableNumber;
  mtd?: NullableNumber;
  weekly?: NullableNumber;
  theme?: string | null;
  primary_theme?: string | null;
  theme_score?: NullableNumber;
  second_theme?: string | null;
  second_theme_score?: NullableNumber;
  theme_confidence?: string | null;
  status?: string;
};

export type PortfolioRow = {
  ticker: string;
  weight?: NullableNumber;
  theme?: string | null;
  base_rank?: NullableNumber;
  tactical_rank?: NullableNumber;
  status?: string;
  ytd?: NullableNumber;
  mtd?: NullableNumber;
  weekly?: NullableNumber;
  primary_theme?: string | null;
  theme_score?: NullableNumber;
  second_theme?: string | null;
  second_theme_score?: NullableNumber;
  theme_confidence?: string | null;
};

export type ThemeReviewRow = {
  ticker: string;
  company_name?: string | null;
  tactical_rank?: NullableNumber;
  base_rank?: NullableNumber;
  sector?: string | null;
  industry?: string | null;
  current_theme?: string | null;
  required?: boolean;
  status?: string;
  note?: string | null;
  reason?: string;
  confidence?: string | null;
  theme_score?: NullableNumber;
  second_theme?: string | null;
  second_theme_score?: NullableNumber;
};

export type ThemeSnapshotRow = {
  ticker: string;
  primary_theme: string;
  theme_score: number;
  second_theme: string;
  second_theme_score: number;
  confidence: string;
  company_name?: string | null;
  sector?: string | null;
  industry?: string | null;
  as_of: string;
};

export type ThemeChangeRow = {
  ticker: string;
  previous_theme: string;
  new_theme: string;
  as_of: string;
  reason: string;
};

export type RankChange = {
  ticker: string;
  previousRank?: NullableNumber;
  currentRank?: NullableNumber;
  rankChange?: NullableNumber;
};

export type Movement = {
  ticker: string;
  previousRank?: NullableNumber;
  currentRank?: NullableNumber;
};

export type ResultDocument = {
  asOf: string;
  status: string;
  marketRegime: Record<string, unknown>;
  dataHealth: {
    status: string;
    ranking_status: string;
    portfolio_status: string;
    universe_count: number;
    base_eligible_count: number;
    tactical_row_count: number;
    tactical_eligible_count: number;
    missing_tickers: string[];
    history_shortage_tickers: string[];
    download_failure_tickers: string[];
    benchmark_sources: Record<string, string>;
    cache_data_status: string;
    regime_data_status: string;
  };
  portfolioStatus: string;
  themeReview: ThemeReviewRow[];
  themeSnapshot?: ThemeSnapshotRow[];
  themeChanges?: ThemeChangeRow[];
  portfolio: PortfolioRow[];
  baseRanking: RankRow[];
  tacticalRanking: TacticalRow[];
  rotation: {
    rankChange: RankChange[];
    portfolioIn: Movement[];
    portfolioOut: Movement[];
    hold: Movement[];
  };
};

export function numberOrNull(value: NullableNumber): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatPercent(value: NullableNumber): string {
  const number = numberOrNull(value);
  if (number === null) return "—";
  const percent = number * 100;
  return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
}

export function formatScore(value: NullableNumber): string {
  const number = numberOrNull(value);
  return number === null ? "—" : number.toFixed(1);
}

export function formatRank(value: NullableNumber): string {
  const number = numberOrNull(value);
  return number === null ? "—" : Number.isInteger(number) ? String(number) : number.toFixed(1);
}

export function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function formatStatus(status: string | null | undefined): string {
  const labels: Record<string, string> = {
    OFFICIAL: "公式",
    INCOMPLETE: "不完全",
    CONFIRMED: "確定",
    RANKING_OFFICIAL_PORTFOLIO_PENDING: "採用銘柄確認待ち",
    THEME_REVIEW_REQUIRED: "テーマ確認待ち",
    THEME_SET: "設定済み",
    PORTFOLIO_INCOMPLETE: "採用銘柄未確定",
    COMPLETE: "完全",
    UNKNOWN: "不明",
  };
  return labels[status ?? ""] ?? status ?? "不明";
}

export function getTacticalStatus(row: TacticalRow): string {
  if (String(row.stage).toLowerCase() === "stage4") return "Rotation";
  const rank = numberOrNull(row.tactical_rank);
  if (rank === null) return "Unranked";
  if (rank <= 10) return "Entry";
  if (rank <= 15) return "Hold";
  return "Rotation";
}

export function activePortfolio(rows: PortfolioRow[]): PortfolioRow[] {
  return rows.filter((row) => (numberOrNull(row.weight) ?? 0) > 0);
}

export function isThemeReviewRequired(row: ThemeReviewRow): boolean {
  return row.required ?? row.current_theme == null;
}

export function regimeScore(regime: Record<string, unknown>): number | null {
  const value = regime.market_regime_score;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function displayRegime(regime: Record<string, unknown>): string {
  const value = typeof regime.regime === "string" ? regime.regime : "UNKNOWN";
  if (value === "RISK_ON") return "Risk ON";
  if (value === "RISK_OFF") return "Risk OFF";
  if (value === "WARNING") return "Warning";
  return "不明";
}

export function stockRankHistory(
  ticker: string,
  result: ResultDocument,
): Array<{ period: string; tacticalRank: number | null }> {
  const current = result.tacticalRanking.find((row) => row.ticker === ticker);
  const movement = result.rotation.rankChange.find((row) => row.ticker === ticker);
  const points: Array<{ period: string; tacticalRank: number | null }> = [];
  if (movement?.previousRank !== null && movement?.previousRank !== undefined) {
    points.push({ period: "前回", tacticalRank: numberOrNull(movement.previousRank) });
  }
  points.push({ period: "今回", tacticalRank: numberOrNull(current?.tactical_rank) });
  return points;
}
