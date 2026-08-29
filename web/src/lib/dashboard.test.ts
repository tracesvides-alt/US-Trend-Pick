import { describe, expect, it } from "vitest";

import {
  activePortfolio,
  displayRegime,
  formatPercent,
  formatStatus,
  getTacticalStatus,
  isThemeReviewRequired,
  stockRankHistory,
} from "./dashboard";

describe("dashboard helpers", () => {
  it("formats returns and missing values for compact mobile cells", () => {
    expect(formatPercent(0.1234)).toBe("+12.3%");
    expect(formatPercent(-0.038)).toBe("-3.8%");
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(null)).toBe("—");
  });

  it("maps operational and regime labels for the Japanese UI", () => {
    expect(formatStatus("INCOMPLETE")).toBe("不完全");
    expect(formatStatus("THEME_REVIEW_REQUIRED")).toBe("テーマ確認待ち");
    expect(formatStatus("THEME_SET")).toBe("設定済み");
    expect(displayRegime({ regime: "RISK_ON" })).toBe("Risk ON");
    expect(displayRegime({ regime: "RISK_OFF" })).toBe("Risk OFF");
  });

  it("identifies Theme Review rows without requiring a Theme editor", () => {
    expect(isThemeReviewRequired({ ticker: "AAA", required: true })).toBe(true);
    expect(isThemeReviewRequired({ ticker: "BBB", current_theme: "Cloud Software", required: false })).toBe(false);
    expect(isThemeReviewRequired({ ticker: "CCC", current_theme: null })).toBe(true);
  });

  it("derives the requested Tactical status buckets", () => {
    expect(getTacticalStatus({ ticker: "AAA", tactical_rank: 3 })).toBe("Entry");
    expect(getTacticalStatus({ ticker: "BBB", tactical_rank: 12 })).toBe("Hold");
    expect(getTacticalStatus({ ticker: "CCC", tactical_rank: 16 })).toBe("Rotation");
    expect(getTacticalStatus({ ticker: "DDD", stage: "Stage4", tactical_rank: 1 })).toBe(
      "Rotation",
    );
  });

  it("keeps only positive-weight Portfolio holdings", () => {
    expect(
      activePortfolio([
        { ticker: "AAA", weight: 0.1 },
        { ticker: "BBB", weight: 0 },
      ]).map((row) => row.ticker),
    ).toEqual(["AAA"]);
  });

  it("uses the single JSON weekly rank history for Stock Detail", () => {
    const result = {
      asOf: "2026-08-29",
      status: "OFFICIAL",
      marketRegime: {},
      dataHealth: {} as never,
      portfolioStatus: "CONFIRMED",
      themeReview: [],
      themeSnapshot: [],
      themeChanges: [],
      portfolio: [],
      baseRanking: [],
      tacticalRanking: [{ ticker: "AAA", tactical_rank: 4 }],
      rotation: {
        rankChange: [{ ticker: "AAA", previousRank: 7, currentRank: 4, rankChange: 3 }],
        portfolioIn: [],
        portfolioOut: [],
        hold: [],
      },
    };

    expect(stockRankHistory("AAA", result)).toEqual([
      { period: "前回", tacticalRank: 7 },
      { period: "今回", tacticalRank: 4 },
    ]);
  });
});
