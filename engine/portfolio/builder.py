"""Theme-constrained weekly Portfolio Builder."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.dates import measurement_date
from engine.portfolio.theme import ThemeRecord, active_theme_map, load_theme_history

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TACTICAL_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"
DEFAULT_THEME_PATH = PROJECT_ROOT / "config" / "theme_history.yaml"
TARGET_HOLDINGS = 10
TARGET_WEIGHT = 0.10


@dataclass(frozen=True)
class PortfolioBuildResult:
    holdings: list[dict[str, Any]]
    theme_review: list[dict[str, Any]]
    portfolio_status: str
    selected_count: int
    rotation_count: int


def _finite(value: Any) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _rank(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _theme(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    value = str(value).strip()
    if not value or value.casefold() in {"unknown", "unclassified", "none", "nan"}:
        return None
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def _is_stage4(row: dict[str, Any]) -> bool:
    return str(row.get("stage", "")).strip().casefold() == "stage4"


def _sorted_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda row: (
            _rank(row.get("tactical_rank")) is None,
            _rank(row.get("tactical_rank")) or float("inf"),
            str(row.get("ticker", "")),
        ),
    )


def theme_constraint_ok(
    candidate: dict[str, Any],
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> bool:
    """Check the 1-theme rule and its explicit 2/3-stock exceptions."""

    theme = _theme(candidate.get("theme"))
    if theme is None:
        return False
    same = [row for row in selected if _theme(row.get("theme")) == theme]
    if not same:
        return True
    candidate_rank = _rank(candidate.get("tactical_rank"))
    if candidate_rank is None:
        return False
    if len(same) == 1:
        if candidate_rank > 10:
            return False
        alternatives = [
            row
            for row in candidates
            if _theme(row.get("theme")) not in (None, theme)
            and (_rank(row.get("tactical_rank")) or float("inf")) > candidate_rank
        ]
        alternatives = _sorted_candidates(alternatives)
        next_alternative_rank = _rank(alternatives[0].get("tactical_rank")) if alternatives else None
        return next_alternative_rank is not None and next_alternative_rank >= 16
    if len(same) == 2:
        return candidate_rank <= 5 and all(
            (_rank(row.get("tactical_rank")) or float("inf")) <= 5 for row in same
        )
    return False


def _portfolio_record(
    row: dict[str, Any],
    theme: str | None,
    status: str,
    weight: float,
) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker", "")).strip().upper(),
        "weight": weight,
        "theme": theme,
        "base_rank": _rank(row.get("base_rank")),
        "tactical_rank": _rank(row.get("tactical_rank")),
        "status": status,
        "ytd": row.get("ytd"),
        "mtd": row.get("mtd"),
        "weekly": row.get("weekly"),
    }


def _review_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker", "")).strip().upper(),
        "tactical_rank": _rank(row.get("tactical_rank")),
        "theme": None,
        "reason": "THEME_REVIEW_REQUIRED",
    }


def _previous_map(previous: list[dict[str, Any]] | pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if previous is None:
        return {}
    records = previous.to_dict("records") if isinstance(previous, pd.DataFrame) else previous
    result: dict[str, dict[str, Any]] = {}
    for row in records:
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        if "weight" in row and _finite(row["weight"]) and float(row["weight"]) <= 0:
            continue
        result[ticker] = dict(row)
    return result


def build_portfolio(
    tactical_ranking: pd.DataFrame,
    theme_map: dict[str, str],
    previous_portfolio: list[dict[str, Any]] | pd.DataFrame | None = None,
    target_holdings: int = TARGET_HOLDINGS,
    target_weight: float = TARGET_WEIGHT,
) -> PortfolioBuildResult:
    """Build a weekly portfolio without changing ranking calculations."""

    candidates = tactical_ranking.to_dict("records")
    for row in candidates:
        ticker = str(row.get("ticker", "")).strip().upper()
        row["ticker"] = ticker
        row["theme"] = _theme(theme_map.get(ticker))
    candidates = _sorted_candidates(
        [row for row in candidates if _rank(row.get("tactical_rank")) is not None]
    )
    by_ticker = {row["ticker"]: row for row in candidates}
    previous = _previous_map(previous_portfolio)
    selected: list[dict[str, Any]] = []
    selected_tickers: set[str] = set()
    rotations: list[dict[str, Any]] = []

    for ticker in previous:
        row = by_ticker.get(ticker)
        if row is None or _is_stage4(row) or (_rank(row.get("tactical_rank")) or float("inf")) > 15:
            old_row = row or {"ticker": ticker, **previous[ticker]}
            rotations.append(_portfolio_record(old_row, _theme(theme_map.get(ticker)), "Rotation", 0.0))
            continue
        if row["theme"] is not None and not theme_constraint_ok(row, selected, candidates):
            rotations.append(_portfolio_record(row, row["theme"], "Rotation", 0.0))
            continue
        status = "Keep" if (_rank(row.get("tactical_rank")) or 99) <= 10 else "Hold"
        if row["theme"] is None:
            status = "THEME_REVIEW_REQUIRED"
        selected.append(row)
        selected_tickers.add(ticker)

    if len(selected) > target_holdings:
        selected = sorted(selected, key=lambda row: _rank(row.get("tactical_rank")) or float("inf"))
        excess = selected[target_holdings:]
        selected = selected[:target_holdings]
        selected_tickers = {row["ticker"] for row in selected}
        rotations.extend(_portfolio_record(row, row["theme"], "Rotation", 0.0) for row in excess)

    for row in candidates:
        if len(selected) >= target_holdings:
            break
        ticker = row["ticker"]
        if ticker in selected_tickers or _is_stage4(row) or not _as_bool(row.get("new_buy")):
            continue
        if row["theme"] is None:
            continue
        if not theme_constraint_ok(row, selected, candidates):
            continue
        selected.append(row)
        selected_tickers.add(ticker)

    top20_unclassified = [
        _review_item(row)
        for row in candidates
        if (_rank(row.get("tactical_rank")) or float("inf")) <= 20 and row["theme"] is None
    ]
    holdings: list[dict[str, Any]] = []
    for row in sorted(selected, key=lambda value: _rank(value.get("tactical_rank")) or float("inf")):
        status = "THEME_REVIEW_REQUIRED" if row["theme"] is None else (
            "Keep" if row["ticker"] in previous and (_rank(row.get("tactical_rank")) or 99) <= 10
            else "Hold" if row["ticker"] in previous else "Entry"
        )
        holdings.append(_portfolio_record(row, row["theme"], status, target_weight))
    holdings.extend(rotations)
    status = (
        "THEME_REVIEW_REQUIRED"
        if top20_unclassified or any(row["theme"] is None for row in selected)
        else "CONFIRMED"
        if len(selected) == target_holdings
        else "PORTFOLIO_INCOMPLETE"
    )
    return PortfolioBuildResult(
        holdings=holdings,
        theme_review=top20_unclassified,
        portfolio_status=status,
        selected_count=len(selected),
        rotation_count=len(rotations),
    )


def _latest_file(directory: str | Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} found in {directory}")
    return files[-1]


def _previous_portfolio_path(as_of: date, directory: str | Path) -> Path | None:
    candidates: list[tuple[date, Path]] = []
    for path in Path(directory).glob("*.json"):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < as_of:
            candidates.append((file_date, path))
    return max(candidates, default=(None, None))[1]


def _load_previous(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return payload.get("holdings", [])


def write_portfolio_output(
    result: PortfolioBuildResult,
    as_of: date,
    output_dir: str | Path = DEFAULT_PORTFOLIO_DIR,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{as_of.isoformat()}.json"
    payload = {
        "as_of": as_of.isoformat(),
        "portfolio_status": result.portfolio_status,
        "holdings": result.holdings,
        "theme_review": result.theme_review,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_portfolio_builder(
    tactical_path: str | Path | None = None,
    theme_path: str | Path = DEFAULT_THEME_PATH,
    previous_path: str | Path | None = None,
    portfolio_dir: str | Path = DEFAULT_PORTFOLIO_DIR,
    as_of: date | None = None,
) -> tuple[PortfolioBuildResult, Path]:
    """Build the portfolio from the latest Tactical Ranking snapshot."""

    output_date = as_of or measurement_date()
    tactical_file = Path(tactical_path) if tactical_path is not None else _latest_file(
        DEFAULT_TACTICAL_DIR, "tactical-*.csv"
    )
    tactical = pd.read_csv(tactical_file)
    records: list[ThemeRecord] = load_theme_history(theme_path)
    themes = active_theme_map(records, output_date)
    if previous_path is None:
        previous_file = _previous_portfolio_path(output_date, portfolio_dir)
    else:
        previous_file = Path(previous_path)
    result = build_portfolio(tactical, themes, _load_previous(previous_file))
    return result, write_portfolio_output(result, output_date, portfolio_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US Trend Pick Theme-constrained Portfolio")
    parser.add_argument("--as-of", default=None, help="Measurement date in YYYY-MM-DD format")
    args = parser.parse_args()
    output_date = date.fromisoformat(args.as_of) if args.as_of else None
    result, output = run_portfolio_builder(as_of=output_date)
    print(f"Portfolio status: {result.portfolio_status}")
    print(f"Selected holdings: {result.selected_count}")
    print(f"Rotation: {result.rotation_count}")
    print(f"Theme Review required: {len(result.theme_review)}")
    print(f"JSON: {output}")
    if result.theme_review:
        print("Theme Review tickers: " + ", ".join(item["ticker"] for item in result.theme_review))


if __name__ == "__main__":
    main()
