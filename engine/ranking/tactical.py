"""Tactical Ranking calculation, output, and batch entry point."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.dates import measurement_date
from engine.ranking.momentum import adjusted_price_series
from engine.ranking.percentile import percentile_score
from engine.ranking.returns import (
    calculate_display_returns,
    calculate_relative_20d_return,
    calculate_rs_drawdown,
)
from engine.ranking.stage import calculate_new_buy, calculate_stage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "market_data" / "prices.parquet"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "market_data" / "metadata.json"
DEFAULT_REGIME_DIR = PROJECT_ROOT / "data" / "results"

HEALTH_WEIGHTS = {
    "relative_20d": 0.30,
    "rs_drawdown_63d": 0.25,
    "dma50_distance": 0.25,
    "dma50_slope": 0.20,
}
REGIME_BASE_WEIGHTS = {
    "RISK_ON": {"momentum": 0.45, "volume": 0.30, "beta": 0.25},
    "WARNING": {"momentum": 0.50, "volume": 0.35, "beta": 0.15},
    "RISK_OFF": {"momentum": 0.55, "volume": 0.35, "beta": 0.10},
}
OUTPUT_COLUMNS = [
    "ticker",
    "base_rank",
    "tactical_rank",
    "rank_change",
    "base_score",
    "regime_base_score",
    "tactical_score",
    "health",
    "penalty",
    "stage",
    "new_buy",
    "ytd",
    "mtd",
    "weekly",
]


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip()))


def _price_groups(price_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if price_data.empty or "ticker" not in price_data.columns:
        return {}
    frame = price_data.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
    return {ticker: rows.reset_index(drop=True) for ticker, rows in frame.groupby("ticker")}


def _linear_score(value: float, points: list[tuple[float, float]]) -> float:
    if not np.isfinite(value):
        return float("nan")
    ordered = sorted(points)
    if value <= ordered[0][0]:
        return float(ordered[0][1])
    if value >= ordered[-1][0]:
        return float(ordered[-1][1])
    for (left_x, left_y), (right_x, right_y) in zip(ordered, ordered[1:]):
        if left_x <= value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return float(left_y + fraction * (right_y - left_y))
    return float("nan")


def rs_drawdown_score(value: float) -> float:
    return _linear_score(
        value,
        [(-0.25, 0.0), (-0.20, 20.0), (-0.15, 40.0), (-0.10, 60.0), (-0.05, 80.0), (0.0, 100.0)],
    )


def dma50_distance_score(value: float) -> float:
    return _linear_score(
        value,
        [(-0.15, 0.0), (-0.10, 10.0), (-0.05, 35.0), (0.0, 60.0), (0.05, 80.0), (0.10, 100.0)],
    )


def dma50_slope_score(value: float) -> float:
    return _linear_score(
        value,
        [(-0.05, 0.0), (-0.025, 30.0), (0.0, 60.0), (0.025, 80.0), (0.05, 100.0)],
    )


def calculate_dma50_distance(data: pd.DataFrame | pd.Series, window: int = 50) -> float:
    prices = adjusted_price_series(data)
    if len(prices) < window:
        return float("nan")
    dma50 = prices.rolling(window).mean().iloc[-1]
    price = prices.iloc[-1]
    if not np.isfinite(dma50) or not np.isfinite(price) or dma50 <= 0:
        return float("nan")
    return float(price / dma50 - 1.0)


def calculate_dma50_slope(
    data: pd.DataFrame | pd.Series,
    window: int = 50,
    periods: int = 20,
) -> float:
    prices = adjusted_price_series(data)
    if len(prices) < window + periods:
        return float("nan")
    dma50 = prices.rolling(window).mean()
    current = dma50.iloc[-1]
    previous = dma50.iloc[-1 - periods]
    if not np.isfinite(current) or not np.isfinite(previous) or previous <= 0:
        return float("nan")
    return float(current / previous - 1.0)


def calculate_health(
    relative_score: float,
    rs_drawdown: float,
    dma50_distance: float,
    dma50_slope: float,
) -> float:
    """Calculate the weighted Tactical Health score."""

    values = {
        "relative_20d": relative_score,
        "rs_drawdown_63d": rs_drawdown_score(rs_drawdown),
        "dma50_distance": dma50_distance_score(dma50_distance),
        "dma50_slope": dma50_slope_score(dma50_slope),
    }
    if any(not np.isfinite(value) for value in values.values()):
        return float("nan")
    return float(sum(values[key] * weight for key, weight in HEALTH_WEIGHTS.items()))


def calculate_penalty(health: float) -> float:
    if not np.isfinite(health) or health >= 50.0:
        return 0.0
    return float(min(40.0, 50.0 - health))


def calculate_regime_base_score(
    momentum_score: float,
    volume_score: float,
    beta_score: float,
    regime: str,
) -> float:
    """Reweight Base component scores according to the Market Regime."""

    if regime not in REGIME_BASE_WEIGHTS:
        raise ValueError(f"unknown regime: {regime}")
    weights = REGIME_BASE_WEIGHTS[regime]
    return float(
        momentum_score * weights["momentum"]
        + volume_score * weights["volume"]
        + beta_score * weights["beta"]
    )


def rank_tactical_scores(scores: pd.Series) -> pd.Series:
    """Rank high Tactical Scores first, using average ranks for ties."""

    return scores.rank(method="average", ascending=False)


def _latest_file(directory: str | Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} found in {directory}")
    return files[-1]


def _load_universe(path: str | Path | None = None) -> pd.DataFrame:
    universe_path = Path(path) if path is not None else _latest_file(DEFAULT_UNIVERSE_DIR, "*.csv")
    return pd.read_csv(universe_path)


def _load_base(path: str | Path | None = None) -> pd.DataFrame:
    base_path = Path(path) if path is not None else _latest_file(DEFAULT_RESULTS_DIR, "base-*.csv")
    return pd.read_csv(base_path)


def _load_regime(path: str | Path | None = None) -> dict[str, Any]:
    regime_path = Path(path) if path is not None else _latest_file(DEFAULT_REGIME_DIR, "regime-*.json")
    return json.loads(regime_path.read_text(encoding="utf-8"))


def _load_benchmark_ticker(metadata_path: str | Path = DEFAULT_METADATA_PATH) -> str:
    path = Path(metadata_path)
    if path.exists():
        metadata = json.loads(path.read_text(encoding="utf-8"))
        ticker = metadata.get("benchmark_sources", {}).get("sp500")
        if ticker:
            return str(ticker).strip().upper()
    return "^GSPC"


def _build_raw_rows(
    universe: pd.DataFrame,
    groups: dict[str, pd.DataFrame],
    benchmark_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    rows: list[dict[str, object]] = []
    exclusions: dict[str, list[str]] = defaultdict(list)
    for ticker in _stable_unique(universe["ticker"]):
        stock = groups.get(ticker)
        if stock is None or stock.empty:
            exclusions[ticker].append("price_data_missing")
            rows.append({"ticker": ticker})
            continue
        relative = calculate_relative_20d_return(stock, benchmark_frame)
        drawdown = calculate_rs_drawdown(stock, benchmark_frame)
        distance = calculate_dma50_distance(stock)
        slope = calculate_dma50_slope(stock)
        stage = calculate_stage(stock)
        display = calculate_display_returns(stock)
        row: dict[str, object] = {
            "ticker": ticker,
            "relative_20d_raw": relative,
            "rs_drawdown_raw": drawdown,
            "dma50_distance_raw": distance,
            "dma50_slope_raw": slope,
            "stage": stage.stage,
            "stage4": stage.stage4,
            "display_ytd": display["ytd"],
            "display_mtd": display["mtd"],
            "display_weekly": display["weekly"],
        }
        for key, value, reason in (
            ("relative_20d_raw", relative, "relative_20d_insufficient"),
            ("rs_drawdown_raw", drawdown, "rs_drawdown_insufficient"),
            ("dma50_distance_raw", distance, "dma50_distance_insufficient"),
            ("dma50_slope_raw", slope, "dma50_slope_insufficient"),
        ):
            if not np.isfinite(value):
                exclusions[ticker].append(reason)
        if stage.status != "OK":
            exclusions[ticker].append("stage_insufficient")
        rows.append(row)
    return pd.DataFrame(rows), dict(exclusions)


def calculate_tactical_ranking(
    universe: pd.DataFrame,
    base_ranking: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark_ticker: str,
    regime: str,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Calculate Tactical Ranking rows for the full Universe."""

    groups = _price_groups(price_data)
    benchmark_frame = groups.get(str(benchmark_ticker).strip().upper(), pd.DataFrame())
    raw, exclusions = _build_raw_rows(universe, groups, benchmark_frame)
    raw["relative_20d_score"] = percentile_score(raw["relative_20d_raw"])
    raw["health"] = raw.apply(
        lambda row: calculate_health(
            row["relative_20d_score"],
            row["rs_drawdown_raw"],
            row["dma50_distance_raw"],
            row["dma50_slope_raw"],
        ),
        axis=1,
    )

    base = base_ranking.copy()
    base["ticker"] = base["ticker"].astype(str).str.strip().str.upper()
    base = base.drop_duplicates("ticker").set_index("ticker")
    output_rows: list[dict[str, object]] = []
    for _, row in raw.iterrows():
        ticker = str(row["ticker"])
        reasons = exclusions.setdefault(ticker, [])
        base_row = base.loc[ticker] if ticker in base.index else None
        if base_row is None:
            reasons.append("base_ranking_unavailable")
        health = row.get("health", float("nan"))
        if not np.isfinite(health):
            reasons.append("health_unavailable")
        stage4 = bool(row.get("stage4", False))
        regime_base_score = float("nan")
        if base_row is not None:
            try:
                regime_base_score = calculate_regime_base_score(
                    float(base_row["momentum_score"]),
                    float(base_row["volume_score"]),
                    float(base_row["beta_score"]),
                    regime,
                )
            except (KeyError, TypeError, ValueError):
                reasons.append("base_component_score_unavailable")
        if not np.isfinite(regime_base_score):
            reasons.append("regime_base_score_unavailable")
        if np.isfinite(health) and np.isfinite(regime_base_score) and not any(
            reason.endswith("insufficient") or reason.endswith("unavailable")
            for reason in reasons
        ):
            penalty = calculate_penalty(health)
            stage_penalty = 15.0 if stage4 else 0.0
            tactical_score = regime_base_score - penalty - stage_penalty
            new_buy = calculate_new_buy(stage4, health)
        else:
            penalty = calculate_penalty(health) if np.isfinite(health) else float("nan")
            tactical_score = float("nan")
            new_buy = False
        output_rows.append(
            {
                "ticker": ticker,
                "base_rank": base_row.get("base_rank", np.nan) if base_row is not None else np.nan,
                "base_score": base_row.get("base_score", np.nan) if base_row is not None else np.nan,
                "regime_base_score": regime_base_score,
                "tactical_score": tactical_score,
                "health": health,
                "penalty": penalty,
                "stage": row.get("stage", "Unknown"),
                "new_buy": new_buy,
                "ytd": row.get("display_ytd", np.nan),
                "mtd": row.get("display_mtd", np.nan),
                "weekly": row.get("display_weekly", np.nan),
            }
        )

    result = pd.DataFrame(output_rows)
    result["tactical_rank"] = rank_tactical_scores(result["tactical_score"])
    result["rank_change"] = result["base_rank"] - result["tactical_rank"]
    result = result[OUTPUT_COLUMNS]
    result = result.sort_values(
        ["tactical_rank", "ticker"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    return result, exclusions


def write_tactical_outputs(
    result: pd.DataFrame,
    as_of: date,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
) -> tuple[Path, Path]:
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"tactical-{as_of.isoformat()}.json"
    csv_path = directory / f"tactical-{as_of.isoformat()}.csv"
    result.to_csv(csv_path, index=False)
    json_path.write_text(
        result.to_json(orient="records", indent=2, force_ascii=False),
        encoding="utf-8",
    )
    return json_path, csv_path


def run_tactical_ranking(
    universe_path: str | Path | None = None,
    base_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    as_of: date | None = None,
) -> tuple[pd.DataFrame, dict[str, list[str]], tuple[Path, Path]]:
    """Load existing Base/Regime artifacts, calculate, and save Tactical outputs."""

    universe = _load_universe(universe_path)
    base = _load_base(base_path)
    regime_payload = _load_regime(regime_path)
    regime = regime_payload.get("regime")
    if regime not in REGIME_BASE_WEIGHTS:
        raise ValueError(f"Regime output has no usable regime state: {regime}")
    prices = pd.read_parquet(cache_path)
    benchmark_ticker = _load_benchmark_ticker(metadata_path)
    result, exclusions = calculate_tactical_ranking(
        universe,
        base,
        prices,
        benchmark_ticker,
        regime,
    )
    output_date = as_of or measurement_date()
    paths = write_tactical_outputs(result, output_date, results_dir)
    return result, exclusions, paths


def _print_summary(
    result: pd.DataFrame,
    exclusions: dict[str, list[str]],
    paths: tuple[Path, Path],
) -> None:
    ranked = result.loc[result["tactical_rank"].notna()]
    print("Tactical Ranking Top30:")
    print(ranked.head(30).to_string(index=False))
    print(f"Universe rows: {len(result)}")
    print(f"Tactical eligible: {len(ranked)}")
    print(f"Unranked: {len(result) - len(ranked)}")
    reason_counts = Counter(
        reason for ticker, reasons in exclusions.items() if ticker in set(result["ticker"])
        for reason in set(reasons)
    )
    for reason, count in sorted(reason_counts.items()):
        print(f"  {reason}: {count}")
    print(f"JSON: {paths[0]}")
    print(f"CSV: {paths[1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate US Trend Pick Tactical Ranking")
    parser.add_argument("--as-of", default=None, help="Output date in YYYY-MM-DD format")
    args = parser.parse_args()
    output_date = date.fromisoformat(args.as_of) if args.as_of else None
    result, exclusions, paths = run_tactical_ranking(as_of=output_date)
    _print_summary(result, exclusions, paths)


if __name__ == "__main__":
    main()
