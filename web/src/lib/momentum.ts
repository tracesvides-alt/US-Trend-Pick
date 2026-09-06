export type MomentumPeriod = "1d" | "5d" | "1mo" | "3mo" | "6mo" | "YTD" | "1y";

export type MomentumRow = {
  ticker: string;
  name?: string | null;
  sector?: string | null;
  price?: number | null;
  return?: number | null;
  signal?: string | null;
  rvol?: number | null;
  rsi?: number | null;
};

export type MomentumRanking = {
  top: MomentumRow[];
  worst: MomentumRow[];
};

export type MomentumIndex = {
  ticker: string;
  name: string;
  emoji?: string | null;
  price?: number | null;
  returns: Partial<Record<MomentumPeriod, number | null>>;
  error?: boolean;
};

export type MomentumSector = {
  sector: string;
  count: number;
  returns: Partial<Record<MomentumPeriod, number | null>>;
  members?: MomentumSectorMember[];
};

export type MomentumSectorMember = {
  ticker: string;
  name?: string | null;
  price?: number | null;
  returns: Partial<Record<MomentumPeriod, number | null>>;
  signal?: string | null;
  rvol?: number | null;
  rsi?: number | null;
};

export type MomentumOverview = {
  asOf: string;
  priceAsOf?: string | null;
  cacheUpdatedAt?: string | null;
  generatedAt: string;
  source: "momentum_master";
  status: "AVAILABLE" | "UNAVAILABLE";
  periods: MomentumPeriod[];
  indices: MomentumIndex[];
  rankings: Partial<Record<MomentumPeriod, MomentumRanking>>;
  sectors: MomentumSector[];
};

export const momentumPeriodLabels: Record<MomentumPeriod, string> = {
  "1d": "本日",
  "5d": "週間",
  "1mo": "1か月",
  "3mo": "3か月",
  "6mo": "6か月",
  YTD: "年初来",
  "1y": "1年間",
};

export function momentumNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatMomentumPercent(value: unknown): string {
  const number = momentumNumber(value);
  if (number === null) return "—";
  return `${number > 0 ? "+" : ""}${number.toFixed(1)}%`;
}

export function formatMomentumTimestamp(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") return "不明";
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return value;
  return `${match[1]}/${match[2]}/${match[3]} ${match[4]}:${match[5]} JST`;
}

export function momentumTone(value: unknown): "positive" | "negative" | "neutral" {
  const number = momentumNumber(value);
  if (number === null || number === 0) return "neutral";
  return number > 0 ? "positive" : "negative";
}

export function safeMomentumOverview(value: unknown): MomentumOverview | null {
  if (!value || typeof value !== "object") return null;
  const document = value as Partial<MomentumOverview>;
  if (document.source !== "momentum_master") return null;
  if (document.status !== "AVAILABLE" && document.status !== "UNAVAILABLE") return null;
  if (!Array.isArray(document.indices) || !Array.isArray(document.sectors)) return null;
  if (!document.rankings || typeof document.rankings !== "object") return null;
  return document as MomentumOverview;
}
