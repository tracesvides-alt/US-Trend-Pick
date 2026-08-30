"""Helpers for storing explainability ranks without changing ranking math."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd


def descending_rank(values: pd.Series) -> pd.Series:
    """Return the average rank with the strongest value at rank one."""

    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    return numeric.rank(method="average", ascending=False)


def rank_change(previous_rank: float | None, current_rank: float | None) -> float | None:
    """Calculate rank improvement as previous rank minus current rank."""

    if previous_rank is None or current_rank is None:
        return None
    if not np.isfinite(previous_rank) or not np.isfinite(current_rank):
        return None
    return float(previous_rank - current_rank)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def previous_rank_map(
    previous_rows: Iterable[Mapping[str, Any]] | None,
    *,
    ticker_key: str = "ticker",
    rank_key: str,
    score_key: str | None = None,
    raw_key: str | None = None,
) -> dict[str, float | None]:
    """Read previous ranks, deriving them from scores for legacy snapshots.

    Older result files did not contain component ranks. When a previous snapshot
    lacks ``rank_key``, the same average-rank rule is applied to its score (or
    raw value) so historical comparisons remain backward compatible.
    """

    rows = [row for row in (previous_rows or []) if isinstance(row, Mapping)]
    if not rows:
        return {}
    direct = {
        str(row.get(ticker_key, "")).strip().upper(): _number(row.get(rank_key))
        for row in rows
        if str(row.get(ticker_key, "")).strip()
    }
    if any(value is not None for value in direct.values()):
        return direct
    value_key = score_key or raw_key
    if value_key is None:
        return direct
    frame = pd.DataFrame(
        [
            {
                "ticker": str(row.get(ticker_key, "")).strip().upper(),
                "value": _number(row.get(value_key)),
            }
            for row in rows
            if str(row.get(ticker_key, "")).strip()
        ]
    )
    if frame.empty:
        return direct
    ranks = descending_rank(frame["value"])
    return {
        ticker: float(rank) if pd.notna(rank) else None
        for ticker, rank in zip(frame["ticker"], ranks, strict=False)
    }


def attach_previous_rank_columns(
    frame: pd.DataFrame,
    previous_rows: Iterable[Mapping[str, Any]] | None,
    specifications: Iterable[tuple[str, str, str, str | None, str | None]],
) -> pd.DataFrame:
    """Add previous-rank and rank-change columns to a ranking DataFrame."""

    result = frame.copy()
    for rank_key, previous_key, change_key, score_key, *raw_key in specifications:
        lookup = previous_rank_map(
            previous_rows,
            rank_key=rank_key,
            score_key=score_key,
            raw_key=raw_key[0] if raw_key else None,
        )
        previous = result["ticker"].map(lookup).astype(float)
        result[previous_key] = previous
        result[change_key] = previous - pd.to_numeric(result[rank_key], errors="coerce")
    return result
