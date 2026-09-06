import { describe, expect, it } from "vitest";

import {
  formatMomentumPercent,
  formatMomentumTimestamp,
  momentumTone,
  safeMomentumOverview,
} from "./momentum";

describe("Momentum Master overview helpers", () => {
  it("formats signed percentage values", () => {
    expect(formatMomentumPercent(12.34)).toBe("+12.3%");
    expect(formatMomentumPercent(-3.8)).toBe("-3.8%");
    expect(formatMomentumPercent(0)).toBe("0.0%");
    expect(formatMomentumPercent(null)).toBe("—");
  });

  it("maps return tones without treating missing data as a loss", () => {
    expect(momentumTone(1)).toBe("positive");
    expect(momentumTone(-1)).toBe("negative");
    expect(momentumTone(0)).toBe("neutral");
    expect(momentumTone(undefined)).toBe("neutral");
  });

  it("labels source cache timestamps as JST without changing the source time", () => {
    expect(formatMomentumTimestamp("2026-02-08 23:09:11")).toBe("2026/02/08 23:09 JST");
    expect(formatMomentumTimestamp(null)).toBe("不明");
  });

  it("rejects malformed optional overview data safely", () => {
    expect(safeMomentumOverview(null)).toBeNull();
    expect(safeMomentumOverview({ source: "other" })).toBeNull();
    expect(
      safeMomentumOverview({
        source: "momentum_master",
        status: "AVAILABLE",
        indices: [],
        rankings: {},
        sectors: [],
      }),
    ).not.toBeNull();
  });
});
