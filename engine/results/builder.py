"""Build and validate the single Frontend result JSON and weekly history."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.dates import measurement_date
from engine.portfolio.theme_review import write_theme_review_output
from engine.results.models import (
    DataHealth,
    PortfolioMovement,
    PortfolioRecord,
    RankChange,
    ResultDocument,
    Rotation,
    ThemeReviewRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "market_data" / "metadata.json"
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values to strict-JSON-safe Python values."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _records(payload: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("records", payload.get(label, []))
    if not isinstance(payload, list):
        raise ValueError(f"{label} output must be a list of records")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"{label} output contains a non-object record")
    return [_json_safe(row) for row in payload]


def _portfolio_rows(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if isinstance(payload, list):
        holdings = payload
        review: Any = []
        portfolio_status = "PORTFOLIO_INCOMPLETE"
    elif isinstance(payload, dict):
        holdings = payload.get("holdings", payload.get("portfolio", []))
        review = payload.get("theme_review", payload.get("themeReview", []))
        portfolio_status = str(
            payload.get("portfolio_status", payload.get("portfolioStatus", "PORTFOLIO_INCOMPLETE"))
        )
    else:
        raise ValueError("portfolio output must be an object or list")
    return _records(holdings, "portfolio"), _records(review, "theme_review"), portfolio_status


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker", "")).strip().upper()


def _rank(row: dict[str, Any], key: str = "tactical_rank") -> float | None:
    value = row.get(key)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _active_portfolio(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = _ticker(row)
        if not ticker:
            continue
        try:
            weight = float(row.get("weight", 0))
        except (TypeError, ValueError):
            weight = 0.0
        if math.isfinite(weight) and weight > 0:
            active[ticker] = row
    return active


def _previous_tactical(payload: dict[str, Any] | None) -> dict[str, float | None]:
    if not payload:
        return {}
    rows = payload.get("tacticalRanking", payload.get("tactical_ranking", []))
    if not isinstance(rows, list):
        return {}
    return {_ticker(row): _rank(row) for row in rows if isinstance(row, dict) and _ticker(row)}


def _movement(
    ticker: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> PortfolioMovement:
    return PortfolioMovement(
        ticker=ticker,
        previousRank=_rank(previous or {}),
        currentRank=_rank(current or {}),
    )


def _weekly_rotation(
    current_tactical: list[dict[str, Any]],
    current_portfolio: list[dict[str, Any]],
    previous_payload: dict[str, Any] | None,
) -> Rotation:
    previous_ranks = _previous_tactical(previous_payload)
    current_ranks = {_ticker(row): _rank(row) for row in current_tactical if _ticker(row)}
    rank_rows: list[RankChange] = []
    for ticker in sorted(set(previous_ranks) | set(current_ranks)):
        previous_rank = previous_ranks.get(ticker)
        current_rank = current_ranks.get(ticker)
        change = (
            previous_rank - current_rank
            if previous_rank is not None and current_rank is not None
            else None
        )
        rank_rows.append(
            RankChange(
                ticker=ticker,
                previousRank=previous_rank,
                currentRank=current_rank,
                rankChange=change,
            )
        )
    rank_rows.sort(
        key=lambda row: (
            row.current_rank is None,
            row.current_rank if row.current_rank is not None else float("inf"),
            row.ticker,
        )
    )

    previous_portfolio: list[dict[str, Any]] = []
    if previous_payload:
        previous_portfolio = previous_payload.get("portfolio", [])
        if not isinstance(previous_portfolio, list):
            previous_portfolio = []
    previous_active = _active_portfolio(previous_portfolio)
    current_active = _active_portfolio(current_portfolio)
    previous_tickers = set(previous_active)
    current_tickers = set(current_active)
    portfolio_in = [
        _movement(ticker, None, current_active[ticker])
        for ticker in sorted(current_tickers - previous_tickers)
    ]
    portfolio_out = [
        _movement(ticker, previous_active[ticker], None)
        for ticker in sorted(previous_tickers - current_tickers)
    ]
    hold = [
        _movement(ticker, previous_active[ticker], current_active[ticker])
        for ticker in sorted(current_tickers & previous_tickers)
    ]
    return Rotation(
        rankChange=rank_rows,
        portfolioIn=portfolio_in,
        portfolioOut=portfolio_out,
        hold=hold,
    )


def _data_health(
    metadata: dict[str, Any],
    regime: dict[str, Any],
    universe_count: int,
    base_rows: list[dict[str, Any]],
    tactical_rows: list[dict[str, Any]],
    portfolio_status: str,
) -> DataHealth:
    cache_status = str(metadata.get("data_status", "INCOMPLETE")).upper()
    regime_status = str(regime.get("data_status", "INCOMPLETE")).upper()
    tactical_eligible = sum(_rank(row) is not None for row in tactical_rows)
    ranking_status = (
        "OFFICIAL"
        if cache_status == "COMPLETE"
        and regime_status == "COMPLETE"
        and len(base_rows) == universe_count
        and tactical_eligible == universe_count
        else "INCOMPLETE"
    )
    missing = {
        str(ticker).strip().upper()
        for ticker in metadata.get("failure_tickers", [])
        if str(ticker).strip()
    }
    missing.update(
        str(ticker).strip().upper()
        for ticker in metadata.get("history_shortage_tickers", [])
        if str(ticker).strip()
    )
    missing.update(
        _ticker(row)
        for row in tactical_rows
        if _ticker(row) and _rank(row) is None
    )
    history_shortage = sorted(
        str(ticker).strip().upper()
        for ticker in metadata.get("history_shortage_tickers", [])
        if str(ticker).strip()
    )
    failures = sorted(
        str(ticker).strip().upper()
        for ticker in metadata.get("failure_tickers", [])
        if str(ticker).strip()
    )
    return DataHealth(
        status="COMPLETE" if ranking_status == "OFFICIAL" else "INCOMPLETE",
        ranking_status=ranking_status,
        portfolio_status=portfolio_status,
        universe_count=universe_count,
        base_eligible_count=len(base_rows),
        tactical_row_count=len(tactical_rows),
        tactical_eligible_count=tactical_eligible,
        missing_tickers=sorted(missing),
        history_shortage_tickers=history_shortage,
        download_failure_tickers=failures,
        benchmark_sources={
            str(key): str(value)
            for key, value in metadata.get("benchmark_sources", {}).items()
        },
        cache_data_status=cache_status,
        regime_data_status=regime_status,
    )


def build_result_document(
    as_of: date,
    base_ranking: list[dict[str, Any]],
    tactical_ranking: list[dict[str, Any]],
    market_regime: dict[str, Any],
    portfolio_payload: dict[str, Any] | list[dict[str, Any]],
    metadata: dict[str, Any],
    universe_count: int,
    previous_result: dict[str, Any] | None = None,
) -> ResultDocument:
    """Build a ResultDocument and validate every output field with Pydantic."""

    base_rows = _records(base_ranking, "base_ranking")
    tactical_rows = _records(tactical_ranking, "tactical_ranking")
    regime = _json_safe(market_regime)
    holdings, review, portfolio_status = _portfolio_rows(portfolio_payload)
    ranking_health = _data_health(
        _json_safe(metadata),
        regime,
        universe_count,
        base_rows,
        tactical_rows,
        portfolio_status,
    )
    overall_status = (
        "INCOMPLETE"
        if ranking_health.ranking_status != "OFFICIAL"
        else "OFFICIAL"
        if portfolio_status == "CONFIRMED"
        else "RANKING_OFFICIAL_PORTFOLIO_PENDING"
    )
    return ResultDocument(
        asOf=as_of,
        status=overall_status,
        marketRegime=regime,
        dataHealth=ranking_health,
        portfolioStatus=portfolio_status,
        themeReview=[ThemeReviewRecord.model_validate(row) for row in review],
        portfolio=[PortfolioRecord.model_validate(row) for row in holdings],
        baseRanking=base_rows,
        tacticalRanking=tactical_rows,
        rotation=_weekly_rotation(tactical_rows, holdings, previous_result),
    )


def _validated_json(document: ResultDocument | dict[str, Any]) -> str:
    validated = ResultDocument.model_validate(document)
    payload = validated.model_dump(mode="json", by_alias=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    ResultDocument.model_validate_json(serialized)
    return serialized + "\n"


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_result_outputs(
    document: ResultDocument | dict[str, Any],
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
) -> tuple[Path, Path]:
    """Validate first, then write the dated history and latest pointer."""

    serialized = _validated_json(document)
    validated = ResultDocument.model_validate_json(serialized)
    output_date = validated.as_of.isoformat()
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    history_path = directory / f"{output_date}.json"
    latest_path = directory / "latest.json"
    _atomic_write(history_path, serialized)
    _atomic_write(latest_path, serialized)
    write_theme_review_output(
        [row.model_dump(mode="json") for row in validated.theme_review],
        directory,
    )
    return history_path, latest_path


def _load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dated_file(
    directory: str | Path,
    prefix: str,
    as_of: date,
) -> Path:
    candidates: list[tuple[date, Path]] = []
    for path in Path(directory).glob(f"{prefix}-*.json"):
        match = _DATE_RE.match(path.stem.removeprefix(f"{prefix}-"))
        if not match:
            continue
        snapshot_date = date.fromisoformat(match.group(1))
        if snapshot_date <= as_of:
            candidates.append((snapshot_date, path))
    if not candidates:
        raise FileNotFoundError(f"No {prefix}-YYYY-MM-DD.json found in {directory}")
    return max(candidates, key=lambda item: item[0])[1]


def _portfolio_file(directory: str | Path, as_of: date) -> Path | None:
    path = Path(directory) / f"{as_of.isoformat()}.json"
    return path if path.exists() else None


def _previous_result_file(directory: str | Path, as_of: date) -> Path | None:
    candidates: list[tuple[date, Path]] = []
    for path in Path(directory).glob("*.json"):
        match = _DATE_RE.match(path.stem)
        if not match:
            continue
        snapshot_date = date.fromisoformat(match.group(1))
        if snapshot_date < as_of:
            candidates.append((snapshot_date, path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _universe_count(path: str | Path) -> int:
    frame = pd.read_csv(path, usecols=["ticker"])
    return int(frame["ticker"].dropna().astype(str).str.strip().str.upper().nunique())


def run_result_builder(
    base_path: str | Path | None = None,
    tactical_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    portfolio_path: str | Path | None = None,
    previous_result_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    portfolio_dir: str | Path = DEFAULT_PORTFOLIO_DIR,
    as_of: date | None = None,
) -> tuple[ResultDocument, tuple[Path, Path]]:
    """Load existing phase artifacts and generate the validated result files."""

    output_date = as_of or measurement_date()
    base_file = Path(base_path) if base_path else _dated_file(results_dir, "base", output_date)
    tactical_file = (
        Path(tactical_path)
        if tactical_path
        else _dated_file(results_dir, "tactical", output_date)
    )
    regime_file = Path(regime_path) if regime_path else _dated_file(results_dir, "regime", output_date)
    portfolio_file = (
        Path(portfolio_path) if portfolio_path else _portfolio_file(portfolio_dir, output_date)
    )
    previous_file = (
        Path(previous_result_path)
        if previous_result_path
        else _previous_result_file(results_dir, output_date)
    )
    universe_file = Path(universe_path) if universe_path else max(
        Path(DEFAULT_UNIVERSE_DIR).glob("*.csv"),
        key=lambda path: path.name,
    )
    metadata_file = Path(metadata_path)
    base_payload = _load_json(base_file, [])
    tactical_payload = _load_json(tactical_file, [])
    regime_payload = _load_json(regime_file, {})
    portfolio_payload = _load_json(portfolio_file, {})
    previous_payload = _load_json(previous_file, None)
    metadata = _load_json(metadata_file, {})
    document = build_result_document(
        output_date,
        _records(base_payload, "base_ranking"),
        _records(tactical_payload, "tactical_ranking"),
        regime_payload,
        portfolio_payload,
        metadata,
        _universe_count(universe_file),
        previous_payload,
    )
    return document, write_result_outputs(document, results_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Frontend-ready US Trend Pick result")
    parser.add_argument("--as-of", default=None, help="Measurement date in YYYY-MM-DD format")
    args = parser.parse_args()
    output_date = date.fromisoformat(args.as_of) if args.as_of else None
    document, paths = run_result_builder(as_of=output_date)
    print(f"Result status: {document.status}")
    print(f"Universe: {document.data_health.universe_count}")
    print(f"Base ranking: {len(document.base_ranking)}")
    print(f"Tactical ranking: {len(document.tactical_ranking)}")
    print(f"Portfolio status: {document.portfolio_status}")
    print(f"Portfolio IN: {len(document.rotation.portfolio_in)}")
    print(f"Portfolio OUT: {len(document.rotation.portfolio_out)}")
    print(f"HOLD: {len(document.rotation.hold)}")
    print(f"History JSON: {paths[0]}")
    print(f"Latest JSON: {paths[1]}")


if __name__ == "__main__":
    main()
