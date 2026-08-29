"""Validation rules for complete and internally consistent market data."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import pandas as pd

from engine.market_data.models import DataStatus, ValidationReport
from engine.market_data.yahoo import PRICE_FIELDS


def _stable_unique(tickers: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))


def _tickers_with_condition(
    data: pd.DataFrame,
    tickers: set[str],
    condition: pd.Series,
) -> list[str]:
    if data.empty or "ticker" not in data:
        return []
    affected = data.loc[condition & data["ticker"].isin(tickers), "ticker"]
    return sorted(set(affected.dropna().astype(str).str.upper()))


def _history_short_tickers(
    data: pd.DataFrame,
    tickers: set[str],
    minimum_history_days: int,
) -> list[str]:
    if data.empty or not {"ticker", "date", "Close"}.issubset(data.columns):
        return sorted(tickers)
    frame = data.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.loc[
        frame["ticker"].isin(tickers) & frame["Close"].notna() & frame["date"].notna()
    ]
    history: dict[str, int] = {}
    for ticker, rows in frame.groupby("ticker"):
        history[str(ticker).upper()] = (rows["date"].max() - rows["date"].min()).days
    return sorted(ticker for ticker in tickers if history.get(ticker, -1) < minimum_history_days)


def validate_price_data(
    data: pd.DataFrame,
    requested_tickers: Iterable[str],
    benchmark_tickers: Iterable[str] = (),
    minimum_history_days: int = 365 * 6,
) -> ValidationReport:
    """Validate Universe and benchmark rows without silently dropping failures."""

    requested_values = [
        str(ticker).strip().upper() for ticker in requested_tickers if str(ticker).strip()
    ]
    requested = _stable_unique(requested_values)
    benchmarks = _stable_unique(benchmark_tickers)
    requested_set = set(requested)
    benchmark_set = set(benchmarks)
    all_required = requested_set | benchmark_set
    errors: list[str] = []

    frame = data.copy() if data is not None else pd.DataFrame()
    missing_columns = [column for column in ["date", "ticker", *PRICE_FIELDS] if column not in frame]
    if missing_columns:
        errors.append(f"missing columns: {', '.join(missing_columns)}")
        frame = pd.DataFrame(columns=["date", "ticker", *PRICE_FIELDS])
    else:
        frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

    requested_counts = Counter(requested_values)
    duplicate_tickers = sorted(
        ticker for ticker, count in requested_counts.items() if count > 1
    )
    duplicate_rows = (
        frame.duplicated(subset=["ticker", "date"], keep=False)
        if {"ticker", "date"}.issubset(frame.columns)
        else pd.Series(dtype=bool)
    )
    duplicate_tickers.extend(
        ticker
        for ticker in _tickers_with_condition(frame, all_required, duplicate_rows)
        if ticker not in duplicate_tickers
    )

    observed = set(frame["ticker"].dropna()) if "ticker" in frame else set()
    missing_tickers = sorted(requested_set - observed)
    benchmark_missing = sorted(benchmark_set - observed)

    close_missing = _tickers_with_condition(frame, all_required, frame["Close"].isna())
    volume_missing = _tickers_with_condition(frame, all_required, frame["Volume"].isna())
    non_positive = _tickers_with_condition(frame, all_required, frame["Close"] <= 0)
    negative_volume = _tickers_with_condition(frame, all_required, frame["Volume"] < 0)
    short_history = _history_short_tickers(frame, requested_set, minimum_history_days)
    short_benchmarks = _history_short_tickers(frame, benchmark_set, minimum_history_days)

    if duplicate_tickers:
        errors.append("duplicate ticker/date rows detected")
    if missing_tickers:
        errors.append("one or more requested Universe tickers are missing")
    if benchmark_missing:
        errors.append("one or more selected benchmark tickers are missing")
    if close_missing:
        errors.append("Close contains missing values")
    if volume_missing:
        errors.append("Volume contains missing values")
    if non_positive:
        errors.append("Close contains non-positive prices")
    if negative_volume:
        errors.append("Volume contains negative values")
    if short_history:
        errors.append("one or more Universe tickers have insufficient history")
    if short_benchmarks:
        errors.append("one or more benchmark tickers have insufficient history")

    invalid = bool(
        missing_columns
        or duplicate_tickers
        or missing_tickers
        or benchmark_missing
        or close_missing
        or volume_missing
        or non_positive
        or negative_volume
        or short_history
        or short_benchmarks
    )
    return ValidationReport(
        data_status=DataStatus.INCOMPLETE if invalid else DataStatus.COMPLETE,
        requested_tickers=len(requested),
        observed_tickers=len(requested_set & observed),
        missing_tickers=missing_tickers,
        benchmark_missing_tickers=benchmark_missing,
        duplicate_tickers=sorted(set(duplicate_tickers)),
        close_missing_tickers=close_missing,
        volume_missing_tickers=volume_missing,
        non_positive_price_tickers=non_positive,
        negative_volume_tickers=negative_volume,
        history_short_tickers=short_history,
        benchmark_history_short_tickers=short_benchmarks,
        errors=errors,
        minimum_history_days=minimum_history_days,
    )
