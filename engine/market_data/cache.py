"""Parquet cache and end-to-end market-data batch pipeline."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from engine.dates import measurement_date, measurement_now
from engine.market_data.models import (
    DEFAULT_BENCHMARKS,
    CacheMetadata,
    ValidationReport,
)
from engine.market_data.validator import validate_price_data
from engine.market_data.yahoo import (
    PRICE_FIELDS,
    default_download_end,
    fetch_benchmarks,
    fetch_market_data,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "market_data" / "prices.parquet"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "market_data" / "metadata.json"
CACHE_COLUMNS = ["date", "ticker", *PRICE_FIELDS]
INITIAL_HISTORY_YEARS = 6
INITIAL_HISTORY_BUFFER_DAYS = 14
UPDATE_SAFETY_MARGIN_DAYS = 7
MINIMUM_HISTORY_DAYS = 365 * INITIAL_HISTORY_YEARS


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=CACHE_COLUMNS)


def normalize_cache_frame(data: pd.DataFrame | None) -> pd.DataFrame:
    """Return a stable, typed, duplicate-free long-format cache frame."""

    if data is None or data.empty:
        return _empty_cache()
    frame = data.copy()
    for column in CACHE_COLUMNS:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[CACHE_COLUMNS]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame["date"] = frame["date"].dt.tz_convert(None).dt.normalize()
    frame["ticker"] = frame["ticker"].astype("string").str.strip().str.upper()
    for field in PRICE_FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=["date", "ticker"])
    frame = frame.dropna(how="all", subset=PRICE_FIELDS)
    frame = frame.drop_duplicates(subset=["ticker", "date"], keep="last")
    return frame.sort_values(["ticker", "date"], ignore_index=True)


def drop_incomplete_latest_session(data: pd.DataFrame | None) -> pd.DataFrame:
    """Remove a provider's still-open latest session from completed-day cache data."""

    frame = normalize_cache_frame(data)
    if frame.empty:
        return frame
    latest_date = frame["date"].max()
    incomplete_latest = (
        frame["date"].eq(latest_date)
        & frame["Close"].isna()
        & frame["Adj Close"].isna()
    )
    return frame.loc[~incomplete_latest].reset_index(drop=True)


def load_cache(path: str | Path = DEFAULT_CACHE_PATH) -> pd.DataFrame:
    """Load an existing Parquet cache, or return an empty typed frame."""

    cache_path = Path(path)
    if not cache_path.exists():
        return _empty_cache()
    return normalize_cache_frame(pd.read_parquet(cache_path))


def merge_price_data(
    existing: pd.DataFrame | None,
    new_data: pd.DataFrame | None,
) -> pd.DataFrame:
    """Merge fresh rows into the cache with last-write-wins per ticker/date."""

    frames = [frame for frame in (existing, new_data) if frame is not None and not frame.empty]
    if not frames:
        return _empty_cache()
    return normalize_cache_frame(pd.concat(frames, ignore_index=True))


def save_cache(
    data: pd.DataFrame,
    path: str | Path = DEFAULT_CACHE_PATH,
    metadata: CacheMetadata | None = None,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
) -> None:
    """Persist prices to Parquet and optional run metadata to JSON."""

    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_cache_frame(data)
    temporary_cache: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_cache = Path(handle.name)
        normalized.to_parquet(temporary_cache, index=False)
        temporary_cache.replace(cache_path)
    finally:
        if temporary_cache is not None:
            temporary_cache.unlink(missing_ok=True)
    if metadata is not None:
        metadata_file = Path(metadata_path)
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            metadata.model_dump(mode="json"), indent=2, ensure_ascii=False
        )
        temporary_metadata: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=metadata_file.parent,
                prefix=f".{metadata_file.name}.",
                suffix=".tmp",
                delete=False,
                mode="w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                temporary_metadata = Path(handle.name)
                handle.write(serialized)
            temporary_metadata.replace(metadata_file)
        finally:
            if temporary_metadata is not None:
                temporary_metadata.unlink(missing_ok=True)


def _initial_start(as_of: date, years: int = INITIAL_HISTORY_YEARS) -> date:
    return (
        pd.Timestamp(as_of)
        - pd.DateOffset(years=years)
        - pd.Timedelta(days=INITIAL_HISTORY_BUFFER_DAYS)
    ).date()


def get_fetch_start(
    tickers: Iterable[str],
    existing: pd.DataFrame | None,
    as_of: date | None = None,
    initial_history_years: int = INITIAL_HISTORY_YEARS,
    safety_margin_days: int = UPDATE_SAFETY_MARGIN_DAYS,
) -> date:
    """Choose initial six-year start or earliest cached end minus a margin."""

    current = as_of or measurement_date()
    requested = {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    cached = normalize_cache_frame(existing)
    if not requested or cached.empty:
        return _initial_start(current, initial_history_years)

    last_dates = cached.loc[cached["ticker"].isin(requested)].groupby("ticker")["date"].max()
    if set(last_dates.index) != requested:
        return _initial_start(current, initial_history_years)
    minimum_cached_date = cached.loc[cached["ticker"].isin(requested), "date"].min()
    exact_required_start = pd.Timestamp(current) - pd.DateOffset(years=initial_history_years)
    if minimum_cached_date > exact_required_start:
        return _initial_start(current, initial_history_years)
    earliest_last = pd.Timestamp(last_dates.min()).date()
    return earliest_last - timedelta(days=safety_margin_days)


def _latest_universe_file(universe_dir: str | Path = DEFAULT_UNIVERSE_DIR) -> Path:
    files = sorted(Path(universe_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No Universe snapshot found in {universe_dir}")
    return files[-1]


def load_universe_tickers(path: str | Path | None = None) -> list[str]:
    """Load normalized tickers from an explicit or latest Universe snapshot."""

    universe_path = Path(path) if path is not None else _latest_universe_file()
    frame = pd.read_csv(universe_path, usecols=["ticker"])
    return frame["ticker"].dropna().astype(str).str.strip().str.upper().tolist()


def _date_or_none(value: object) -> date | None:
    if value is None:
        return None
    converted = pd.to_datetime(value, errors="coerce")
    if pd.isna(converted):
        return None
    return converted.date()


def _benchmark_cache_ready(existing: pd.DataFrame) -> bool:
    """Return whether at least one configured benchmark source has six years."""

    if existing.empty:
        return False
    candidates = {
        ticker
        for spec in DEFAULT_BENCHMARKS
        for ticker in (spec.index_ticker, spec.proxy_ticker)
    }
    for ticker, rows in existing.loc[existing["ticker"].isin(candidates)].groupby("ticker"):
        close_rows = rows.loc[rows["Close"].notna()]
        if close_rows.empty:
            continue
        if (close_rows["date"].max() - close_rows["date"].min()).days >= MINIMUM_HISTORY_DAYS:
            return True
    return False


def _pipeline_metadata(
    *,
    as_of: date,
    download_start: date,
    download_end: date,
    universe_count: int,
    successful_count: int,
    failures: dict[str, str],
    validation: ValidationReport,
    cache: pd.DataFrame,
    benchmark_sources: dict[str, str],
    benchmark_failures: dict[str, str],
) -> CacheMetadata:
    cache = normalize_cache_frame(cache)
    return CacheMetadata(
        generated_at=measurement_now(),
        as_of=as_of,
        data_status=validation.data_status,
        universe_count=universe_count,
        download_success=successful_count,
        failure_count=len(failures),
        failure_tickers=sorted(failures),
        history_shortage_count=len(validation.history_short_tickers),
        history_shortage_tickers=validation.history_short_tickers,
        cache_ticker_count=cache["ticker"].nunique(),
        cache_row_count=len(cache),
        cache_start=_date_or_none(cache["date"].min() if not cache.empty else None),
        cache_end=_date_or_none(cache["date"].max() if not cache.empty else None),
        download_start=download_start,
        download_end=download_end,
        benchmark_sources=benchmark_sources,
        benchmark_failures=benchmark_failures,
        validation=validation.model_dump(mode="json"),
    )


def build_market_data_cache(
    universe_path: str | Path | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    as_of: date | None = None,
    chunk_size: int = 75,
    timeout: int = 30,
) -> tuple[pd.DataFrame, CacheMetadata]:
    """Download the full Universe plus benchmarks and update the Parquet cache."""

    current = as_of or measurement_date()
    universe_tickers = load_universe_tickers(universe_path)
    existing = load_cache(cache_path)
    start = get_fetch_start(universe_tickers, existing, current)
    end = default_download_end(current)

    download = fetch_market_data(
        universe_tickers,
        start=start,
        end=end,
        chunk_size=chunk_size,
        timeout=timeout,
    )
    benchmark_start = start if _benchmark_cache_ready(existing) else _initial_start(current)
    benchmarks = fetch_benchmarks(
        start=benchmark_start,
        end=end,
        chunk_size=chunk_size,
        timeout=timeout,
        minimum_history_days=MINIMUM_HISTORY_DAYS,
        existing=existing,
    )
    fresh = pd.concat(
        [frame for frame in (download.data, benchmarks.data) if not frame.empty],
        ignore_index=True,
    ) if not download.data.empty or not benchmarks.data.empty else _empty_cache()
    merged = drop_incomplete_latest_session(merge_price_data(existing, fresh))

    validation = validate_price_data(
        merged,
        requested_tickers=universe_tickers,
        benchmark_tickers=list(benchmarks.used_tickers.values()),
        minimum_history_days=MINIMUM_HISTORY_DAYS,
    )
    metadata = _pipeline_metadata(
        as_of=current,
        download_start=start,
        download_end=end,
        universe_count=len(universe_tickers),
        successful_count=len(download.successful_tickers),
        failures=download.failures,
        validation=validation,
        cache=merged,
        benchmark_sources=benchmarks.used_tickers,
        benchmark_failures=benchmarks.failures,
    )
    save_cache(merged, cache_path, metadata, metadata_path)
    return merged, metadata


def _print_summary(metadata: CacheMetadata) -> None:
    print(f"Universe count: {metadata.universe_count}")
    print(f"Download success: {metadata.download_success}")
    print(f"Failure: {metadata.failure_count}")
    print(f"History不足: {metadata.history_shortage_count}")
    print(f"Cache保存Ticker件数: {metadata.cache_ticker_count}")
    print(f"Cache保存行数: {metadata.cache_row_count}")
    print(f"data_status: {metadata.data_status.value}")
    print(f"Benchmark sources: {metadata.benchmark_sources}")
    if metadata.benchmark_failures:
        print(f"Benchmark failures: {metadata.benchmark_failures}")
    if metadata.failure_tickers:
        print(f"Failure tickers: {', '.join(metadata.failure_tickers)}")


def main() -> None:
    _, metadata = build_market_data_cache()
    _print_summary(metadata)


if __name__ == "__main__":
    main()
