"""Yahoo Finance download helpers with normalization and retry handling."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from engine.dates import measurement_date
from engine.market_data.models import (
    DEFAULT_BENCHMARKS,
    BenchmarkResult,
    BenchmarkSpec,
    DownloadResult,
)

PRICE_FIELDS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")
DEFAULT_CHUNK_SIZE = 75
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_ATTEMPTS = 3


class YahooDownloadError(RuntimeError):
    """Raised when Yahoo returns no usable frame for a requested chunk."""


def _unique_tickers(tickers: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return stable unique tickers and the duplicate values found."""

    unique: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for value in tickers:
        ticker = str(value).strip().upper()
        if not ticker:
            continue
        if ticker in seen:
            if ticker not in duplicates:
                duplicates.append(ticker)
            continue
        seen.add(ticker)
        unique.append(ticker)
    return unique, duplicates


def _column_key(value: Any) -> str:
    return str(value).strip().casefold().replace("_", " ")


def _field_name(value: Any) -> str | None:
    normalized = " ".join(_column_key(value).split())
    aliases = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adj close": "Adj Close",
        "adjusted close": "Adj Close",
        "adjclose": "Adj Close",
        "volume": "Volume",
    }
    return aliases.get(normalized)


def _ticker_key(value: Any) -> str:
    return str(value).strip().upper()


def _date_index(raw: pd.DataFrame) -> pd.DatetimeIndex:
    """Extract a timezone-free normalized daily index from a Yahoo frame."""

    index: Any = raw.index
    if isinstance(index, pd.RangeIndex) and "Date" in raw.columns:
        index = raw["Date"]
    dates = pd.to_datetime(index, errors="coerce", utc=True)
    if isinstance(dates, pd.Series):
        dates = pd.DatetimeIndex(dates)
    return dates.tz_convert(None).normalize()


def _simple_field_columns(raw: pd.DataFrame, tickers: Sequence[str]) -> dict[str, Any]:
    """Map simple (single-ticker) columns to canonical field names."""

    if len(tickers) != 1:
        return {}
    fields: dict[str, Any] = {}
    for column in raw.columns:
        field = _field_name(column)
        if field is not None:
            fields[field] = column
    return fields


def _multi_field_columns(
    raw: pd.DataFrame,
    ticker: str,
) -> dict[str, Any]:
    """Find fields regardless of whether Yahoo uses (field, ticker) or (ticker, field)."""

    fields: dict[str, Any] = {}
    expected_ticker = _ticker_key(ticker)
    if not isinstance(raw.columns, pd.MultiIndex):
        return fields
    for column in raw.columns:
        values = list(column)
        tickers_in_column = {_ticker_key(value) for value in values}
        if expected_ticker not in tickers_in_column:
            continue
        for value in values:
            field = _field_name(value)
            if field is not None:
                fields[field] = column
                break
    return fields


def _empty_series(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.nan, index=index, dtype="float64")


def _normalize_one_ticker(
    raw: pd.DataFrame,
    ticker: str,
    requested_tickers: Sequence[str],
) -> pd.DataFrame | None:
    """Convert one ticker from a Yahoo frame into the canonical long format."""

    if raw.empty:
        return None
    index = _date_index(raw)
    if index.isna().all():
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        columns = _multi_field_columns(raw, ticker)
    else:
        columns = _simple_field_columns(raw, requested_tickers)
    if not columns:
        return None

    values: dict[str, pd.Series] = {}
    for field in PRICE_FIELDS:
        if field in columns:
            values[field] = pd.to_numeric(raw[columns[field]], errors="coerce")
        else:
            values[field] = _empty_series(index)
    if "Adj Close" not in columns and "Close" in columns:
        values["Adj Close"] = values["Close"].copy()

    frame = pd.DataFrame(values, index=index)
    frame.index.name = "date"
    frame = frame.loc[~frame.index.isna()]
    frame = frame.dropna(how="all", subset=PRICE_FIELDS)
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.reset_index()
    frame.insert(1, "ticker", ticker)
    return frame[["date", "ticker", *PRICE_FIELDS]]


def normalize_download_columns(
    raw: pd.DataFrame | None,
    requested_tickers: Sequence[str],
) -> dict[str, pd.DataFrame]:
    """Normalize common yfinance column layouts into one frame per ticker.

    yfinance has returned both flat columns for a single ticker and MultiIndex
    columns for multi-ticker requests. The field/ticker level order has also
    varied, so this function identifies each value by name instead of relying
    on a fixed level position.
    """

    if raw is None or raw.empty:
        return {}
    tickers, _ = _unique_tickers(requested_tickers)
    normalized: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        frame = _normalize_one_ticker(raw, ticker, tickers)
        if frame is not None and not frame.empty:
            normalized[ticker] = frame
    return normalized


@retry(
    stop=stop_after_attempt(DEFAULT_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def download_chunk(
    tickers: Sequence[str],
    start: date,
    end: date | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Download a chunk and retry transient/provider failures up to three times."""

    raw = yf.download(
        list(tickers),
        start=start,
        end=end,
        actions=False,
        auto_adjust=False,
        group_by="column",
        progress=False,
        threads=True,
        timeout=timeout,
    )
    if raw is None or raw.empty:
        raise YahooDownloadError("Yahoo returned an empty frame")
    return raw


def _chunked(values: Sequence[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def fetch_market_data(
    tickers: Iterable[str],
    start: date,
    end: date | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> DownloadResult:
    """Download all requested tickers in chunks and report missing symbols."""

    unique, duplicates = _unique_tickers(tickers)
    chunks = _chunked(unique, chunk_size)
    frames: list[pd.DataFrame] = []
    successful: set[str] = set()
    failures: dict[str, str] = {}

    for chunk in chunks:
        try:
            raw = download_chunk(chunk, start=start, end=end, timeout=timeout)
            normalized = normalize_download_columns(raw, chunk)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures.update({ticker: reason for ticker in chunk})
            continue

        frames.extend(normalized.values())
        successful.update(normalized)
        for ticker in chunk:
            if ticker not in normalized:
                failures[ticker] = "ticker was not returned by Yahoo"

    data = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["date", "ticker", *PRICE_FIELDS])
    )
    return DownloadResult(
        data=data,
        requested_tickers=unique,
        successful_tickers=successful,
        failures=failures,
        duplicate_tickers=duplicates,
        chunks=chunks,
    )


def _has_usable_history(data: pd.DataFrame, ticker: str, minimum_history_days: int) -> bool:
    if data.empty or "ticker" not in data or "date" not in data:
        return False
    rows = data.loc[(data["ticker"] == ticker) & data["Close"].notna()]
    if rows.empty:
        return False
    dates = pd.to_datetime(rows["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    return (dates.max() - dates.min()).days >= minimum_history_days


def fetch_benchmarks(
    start: date,
    end: date | None = None,
    specs: Sequence[BenchmarkSpec] = DEFAULT_BENCHMARKS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    minimum_history_days: int = 365 * 6,
    existing: pd.DataFrame | None = None,
) -> BenchmarkResult:
    """Fetch index benchmarks, falling back to configured ETFs when needed."""

    selected_frames: list[pd.DataFrame] = []
    used_tickers: dict[str, str] = {}
    failures: dict[str, str] = {}
    fallback_reasons: dict[str, str] = {}

    direct = fetch_market_data(
        [spec.index_ticker for spec in specs],
        start=start,
        end=end,
        chunk_size=chunk_size,
        timeout=timeout,
    )
    for spec in specs:
        direct_data = direct.data.loc[
            direct.data["ticker"].eq(spec.index_ticker)
        ].copy()
        direct_history_frames = [
            frame for frame in (existing, direct_data) if frame is not None and not frame.empty
        ]
        direct_history = (
            pd.concat(direct_history_frames, ignore_index=True)
            if direct_history_frames
            else direct_data
        )
        direct_ok = (
            spec.index_ticker in direct.successful_tickers
            and direct_data["ticker"].nunique() == 1
            and _has_usable_history(
                direct_history,
                spec.index_ticker,
                minimum_history_days,
            )
        )
        if direct_ok:
            used_tickers[spec.name] = spec.index_ticker
            selected_frames.append(direct_data)
            continue

        reason = direct.failures.get(spec.index_ticker, "insufficient benchmark history")
        if not spec.allow_proxy:
            failures[spec.name] = reason
            continue

        proxy = fetch_market_data(
            [spec.proxy_ticker],
            start=start,
            end=end,
            chunk_size=chunk_size,
            timeout=timeout,
        )
        proxy_history_frames = [
            frame for frame in (existing, proxy.data) if frame is not None and not frame.empty
        ]
        proxy_history = (
            pd.concat(proxy_history_frames, ignore_index=True)
            if proxy_history_frames
            else proxy.data
        )
        proxy_ok = (
            not proxy.failures
            and _has_usable_history(
                proxy_history,
                spec.proxy_ticker,
                minimum_history_days,
            )
        )
        if proxy_ok:
            used_tickers[spec.name] = spec.proxy_ticker
            selected_frames.append(proxy.data)
            fallback_reasons[spec.name] = reason
        else:
            failures[spec.name] = proxy.failures.get(
                spec.proxy_ticker,
                f"index failed ({reason}); proxy history insufficient",
            )

    data = (
        pd.concat(selected_frames, ignore_index=True)
        if selected_frames
        else pd.DataFrame(columns=["date", "ticker", *PRICE_FIELDS])
    )
    return BenchmarkResult(
        data=data,
        used_tickers=used_tickers,
        failures=failures,
        fallback_reasons=fallback_reasons,
    )


def default_download_end(as_of: date | None = None) -> date:
    """Return the exclusive end date that includes the last completed session."""

    return as_of or measurement_date()
