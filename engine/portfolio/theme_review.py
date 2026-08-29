"""Compatibility coverage output for automatic Theme snapshots."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from engine.results.models import ThemeReviewRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"
THEME_REVIEW_LIMIT = 30


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metadata_by_ticker(universe: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if universe is None or universe.empty or "ticker" not in universe.columns:
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for row in universe.to_dict("records"):
        ticker = _text(row.get("ticker"))
        if ticker:
            metadata[ticker.upper()] = row
    return metadata


def build_theme_review(
    tactical_ranking: pd.DataFrame,
    universe: pd.DataFrame | None,
    active_themes: dict[str, str],
    theme_details: dict[str, dict[str, Any]] | None = None,
    limit: int = THEME_REVIEW_LIMIT,
) -> list[dict[str, Any]]:
    """Expose automatic Theme coverage for the ranked Tactical top N rows."""

    if tactical_ranking.empty or "ticker" not in tactical_ranking.columns:
        return []
    ranked = tactical_ranking.copy()
    ranked["ticker"] = ranked["ticker"].astype(str).str.strip().str.upper()
    ranked["_rank"] = pd.to_numeric(ranked.get("tactical_rank"), errors="coerce")
    ranked = ranked.dropna(subset=["_rank"])
    ranked = ranked.sort_values(["_rank", "ticker"], kind="stable").head(limit)
    metadata = _metadata_by_ticker(universe)
    review: list[dict[str, Any]] = []
    for row in ranked.to_dict("records"):
        ticker = str(row["ticker"]).strip().upper()
        current_theme = active_themes.get(ticker) or "Other"
        detail = (theme_details or {}).get(ticker, {})
        source = {**detail, **metadata.get(ticker, {}), **row}
        review.append(
            {
                "ticker": ticker,
                "company_name": _text(source.get("company_name")),
                "tactical_rank": _number(source.get("tactical_rank")),
                "base_rank": _number(source.get("base_rank")),
                "sector": _text(source.get("sector")),
                "industry": _text(source.get("industry")),
                "current_theme": current_theme,
                "required": False,
                "status": "THEME_SET",
                "confidence": detail.get("confidence"),
                "theme_score": detail.get("theme_score"),
                "second_theme": detail.get("second_theme"),
                "second_theme_score": detail.get("second_theme_score"),
            }
        )
    return review


def write_theme_review_output(
    records: list[dict[str, Any]],
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Validate and write the standalone Theme review list."""

    validated = [
        ThemeReviewRecord.model_validate(record).model_dump(mode="json")
        for record in records
    ]
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "theme-review.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(validated, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
    return path
