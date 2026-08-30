"""Base Trend Ranking batch and output generation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from engine.dates import measurement_date
from engine.ranking.beta import BetaMetrics, calculate_beta
from engine.ranking.explanations import attach_previous_rank_columns, descending_rank
from engine.ranking.momentum import calculate_momentum
from engine.ranking.percentile import percentile_score
from engine.ranking.volume import calculate_dollar_volume_expansion

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "market_data" / "prices.parquet"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "market_data" / "metadata.json"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"
OUTPUT_COLUMNS = [
    "ticker",
    "momentum_raw",
    "momentum_score",
    "volume_expansion_raw",
    "volume_score",
    "beta_raw",
    "beta_score",
    "base_score",
    "base_rank",
    "momentum_rank",
    "momentum_previous_rank",
    "momentum_rank_change",
    "volume_expansion_rank",
    "volume_expansion_previous_rank",
    "volume_expansion_rank_change",
    "beta_rank",
    "beta_previous_rank",
    "beta_rank_change",
    "base_previous_rank",
    "base_rank_change",
]


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip()))


def _latest_universe_file(universe_dir: str | Path = DEFAULT_UNIVERSE_DIR) -> Path:
    files = sorted(Path(universe_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No Universe snapshot found in {universe_dir}")
    return files[-1]


def _load_tickers(universe_path: str | Path | None = None) -> list[str]:
    path = Path(universe_path) if universe_path is not None else _latest_universe_file()
    return _stable_unique(pd.read_csv(path, usecols=["ticker"])["ticker"].dropna())


def _group_prices(price_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if price_data.empty or "ticker" not in price_data.columns:
        return {}
    frame = price_data.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
    return {ticker: rows.reset_index(drop=True) for ticker, rows in frame.groupby("ticker")}


def _metric_failure_reasons(
    price_frame: pd.DataFrame | None,
    benchmark_frame: pd.DataFrame | None,
) -> tuple[float, float, BetaMetrics | None, list[str]]:
    if price_frame is None or price_frame.empty:
        return float("nan"), float("nan"), None, ["price_data_missing"]
    reasons: list[str] = []
    momentum_raw = calculate_momentum(price_frame)
    if not np.isfinite(momentum_raw):
        reasons.append("momentum_insufficient_history_or_price")
    volume_raw = calculate_dollar_volume_expansion(price_frame)
    if not np.isfinite(volume_raw):
        reasons.append("volume_insufficient_history_or_price")
    if benchmark_frame is None or benchmark_frame.empty:
        beta_metrics = None
        reasons.append("benchmark_data_missing")
    else:
        beta_metrics = calculate_beta(price_frame, benchmark_frame)
        if beta_metrics.beta_raw is None:
            reasons.append(beta_metrics.status.lower())
    return momentum_raw, volume_raw, beta_metrics, reasons


def calculate_base_score(
    momentum_score: float,
    volume_score: float,
    beta_score: float,
) -> float:
    """Apply the Base component weights: 45% / 30% / 25%."""

    return float(momentum_score * 0.45 + volume_score * 0.30 + beta_score * 0.25)


def calculate_base_ranking(
    universe_tickers: Iterable[str],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    benchmark_ticker: str,
    previous_ranking: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Calculate Base scores for every Universe ticker using identical rules."""

    tickers = _stable_unique(universe_tickers)
    groups = _group_prices(price_data)
    benchmark_frame = groups.get(str(benchmark_ticker).strip().upper())
    if benchmark_frame is None:
        benchmark_frame = _group_prices(benchmark_data).get(
            str(benchmark_ticker).strip().upper()
        )

    rows: list[dict[str, object]] = []
    excluded: dict[str, list[str]] = defaultdict(list)
    for ticker in tickers:
        momentum_raw, volume_raw, beta_metrics, reasons = _metric_failure_reasons(
            groups.get(ticker), benchmark_frame
        )
        if beta_metrics is None or beta_metrics.beta_raw is None:
            if not reasons:
                reasons.append("beta_unavailable")
        if reasons:
            excluded[ticker].extend(reasons)
            continue
        rows.append(
            {
                "ticker": ticker,
                "momentum_raw": momentum_raw,
                "volume_expansion_raw": volume_raw,
                "beta_raw": beta_metrics.beta_raw,
                "_beta_neutral": beta_metrics.beta_score == 50.0,
            }
        )

    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), dict(excluded)
    result = pd.DataFrame(rows)
    result["momentum_score"] = percentile_score(result["momentum_raw"])
    result["volume_score"] = percentile_score(result["volume_expansion_raw"])
    result["beta_score"] = float("nan")
    neutral = result["_beta_neutral"]
    result.loc[neutral, "beta_score"] = 50.0
    beta_population = result.loc[~neutral, "beta_raw"]
    result.loc[~neutral, "beta_score"] = percentile_score(beta_population)
    result["base_score"] = result.apply(
        lambda row: calculate_base_score(
            row["momentum_score"],
            row["volume_score"],
            row["beta_score"],
        ),
        axis=1,
    )
    result["base_rank"] = result["base_score"].rank(method="average", ascending=False)
    result["momentum_rank"] = descending_rank(result["momentum_score"])
    result["volume_expansion_rank"] = descending_rank(result["volume_score"])
    result["beta_rank"] = descending_rank(result["beta_score"])
    result = attach_previous_rank_columns(
        result,
        None if previous_ranking is None else previous_ranking.to_dict(orient="records"),
        [
            ("momentum_rank", "momentum_previous_rank", "momentum_rank_change", "momentum_score", "momentum_raw"),
            ("volume_expansion_rank", "volume_expansion_previous_rank", "volume_expansion_rank_change", "volume_score", "volume_expansion_raw"),
            ("beta_rank", "beta_previous_rank", "beta_rank_change", "beta_score", "beta_raw"),
            ("base_rank", "base_previous_rank", "base_rank_change", "base_score", None),
        ],
    )
    result = result.sort_values(["base_rank", "ticker"], kind="stable")
    return result[OUTPUT_COLUMNS].reset_index(drop=True), dict(excluded)


def _read_benchmark_ticker(metadata_path: str | Path = DEFAULT_METADATA_PATH) -> str:
    path = Path(metadata_path)
    if path.exists():
        metadata = json.loads(path.read_text(encoding="utf-8"))
        ticker = metadata.get("benchmark_sources", {}).get("sp500")
        if ticker:
            return str(ticker).strip().upper()
    return "^GSPC"


def _previous_base_path(
    results_dir: str | Path,
    as_of: date,
) -> Path | None:
    candidates: list[tuple[date, Path]] = []
    for path in Path(results_dir).glob("base-*.json"):
        try:
            snapshot_date = date.fromisoformat(path.stem.removeprefix("base-"))
        except ValueError:
            continue
        if snapshot_date < as_of:
            candidates.append((snapshot_date, path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _load_previous_base(path: Path | None) -> pd.DataFrame | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(payload if isinstance(payload, list) else payload.get("records", []))


def write_base_outputs(
    result: pd.DataFrame,
    as_of: date,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
) -> tuple[Path, Path]:
    """Write the requested JSON and CSV Base Ranking files."""

    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"base-{as_of.isoformat()}.json"
    csv_path = directory / f"base-{as_of.isoformat()}.csv"
    result.to_csv(csv_path, index=False)
    json_path.write_text(
        result.to_json(orient="records", indent=2, force_ascii=False),
        encoding="utf-8",
    )
    return json_path, csv_path


def run_base_ranking(
    universe_path: str | Path | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    as_of: date | None = None,
    previous_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, list[str]], tuple[Path, Path]]:
    """Load Phase 1/2 artifacts, calculate all Base metrics, and save outputs."""

    output_date = as_of or measurement_date()
    tickers = _load_tickers(universe_path)
    prices = pd.read_parquet(cache_path)
    benchmark_ticker = _read_benchmark_ticker(metadata_path)
    previous_file = Path(previous_path) if previous_path else _previous_base_path(results_dir, output_date)
    previous = _load_previous_base(previous_file)
    result, excluded = calculate_base_ranking(
        tickers,
        prices,
        prices,
        benchmark_ticker,
        previous_ranking=previous,
    )
    paths = write_base_outputs(result, output_date, results_dir)
    return result, excluded, paths


def _print_summary(
    result: pd.DataFrame,
    excluded: dict[str, list[str]],
    paths: tuple[Path, Path],
) -> None:
    print("Base Ranking Top20:")
    print(result.head(20).to_string(index=False))
    print(f"Eligible: {len(result)}")
    print(f"Excluded data-insufficient: {len(excluded)}")
    reason_counts = Counter(reason for reasons in excluded.values() for reason in reasons)
    for reason, count in sorted(reason_counts.items()):
        print(f"  {reason}: {count}")
    print(f"JSON: {paths[0]}")
    print(f"CSV: {paths[1]}")


def main() -> None:
    result, excluded, paths = run_base_ranking()
    _print_summary(result, excluded, paths)


if __name__ == "__main__":
    main()
