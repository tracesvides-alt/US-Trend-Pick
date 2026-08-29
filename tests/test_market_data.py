from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from engine.dates import measurement_date
from engine.market_data import cache, yahoo
from engine.market_data.models import BenchmarkSpec, DataStatus, DownloadResult
from engine.market_data.validator import validate_price_data


FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def make_yahoo_frame(tickers: list[str], periods: int = 3) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    columns: list[tuple[str, str]] = []
    values: dict[tuple[str, str], list[float]] = {}
    for ticker_index, ticker in enumerate(tickers):
        for field_index, field in enumerate(FIELDS):
            column = (field, ticker)
            columns.append(column)
            values[column] = [
                float(10 + ticker_index + field_index + day)
                for day in range(periods)
            ]
    return pd.DataFrame(values, index=dates).reindex(columns=pd.MultiIndex.from_tuples(columns))


def make_long_frame(tickers: list[str], periods: int = 7) -> pd.DataFrame:
    raw = make_yahoo_frame(tickers, periods=periods)
    frames = list(yahoo.normalize_download_columns(raw, tickers).values())
    return pd.concat(frames, ignore_index=True)


def test_fetch_market_data_chunks_and_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_download_chunk(tickers, start, end=None, timeout=30):
        calls.append(list(tickers))
        returned = [ticker for ticker in tickers if ticker != "MISSING"]
        return make_yahoo_frame(returned)

    monkeypatch.setattr(yahoo, "download_chunk", fake_download_chunk)
    result = yahoo.fetch_market_data(
        ["AAA", "BBB", "MISSING", "DDD", "AAA"],
        start=date(2024, 1, 1),
        chunk_size=2,
    )

    assert calls == [["AAA", "BBB"], ["MISSING", "DDD"]]
    assert result.successful_tickers == {"AAA", "BBB", "DDD"}
    assert result.failures == {"MISSING": "ticker was not returned by Yahoo"}
    assert result.duplicate_tickers == ["AAA"]


def test_download_chunk_retries_three_times(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def flaky_download(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary failure")
        return make_yahoo_frame(["AAA"])

    monkeypatch.setattr(yahoo.yf, "download", flaky_download)
    monkeypatch.setattr(yahoo.download_chunk.retry, "sleep", lambda _: None)
    result = yahoo.download_chunk(["AAA"], start=date(2024, 1, 1))

    assert attempts == 3
    assert not result.empty


def test_normalize_handles_ticker_first_multiindex_and_adj_close_fallback() -> None:
    raw = make_yahoo_frame(["AAA"])
    raw = raw.swaplevel(0, 1, axis=1)
    raw = raw.drop(columns=[("AAA", "Adj Close")])

    normalized = yahoo.normalize_download_columns(raw, ["AAA"])

    assert list(normalized["AAA"].columns) == ["date", "ticker", *FIELDS]
    pd.testing.assert_series_equal(
        normalized["AAA"]["Close"],
        normalized["AAA"]["Adj Close"],
        check_names=False,
    )


def test_merge_is_last_write_wins_per_ticker_and_date(tmp_path) -> None:
    old = make_long_frame(["AAA"], periods=2)
    new = old.iloc[[1]].copy()
    new.loc[:, "Close"] = 999

    merged = cache.merge_price_data(old, new)
    assert len(merged) == 2
    assert merged.loc[merged["date"] == pd.Timestamp("2024-01-02"), "Close"].item() == 999

    path = tmp_path / "prices.parquet"
    cache.save_cache(merged, path)
    loaded = cache.load_cache(path)
    assert len(loaded) == 2
    assert loaded["ticker"].tolist() == ["AAA", "AAA"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_measurement_date_converts_utc_boundary_to_jst() -> None:
    utc_boundary = pd.Timestamp("2026-08-28 23:30:00+00:00").to_pydatetime()

    assert measurement_date(utc_boundary) == date(2026, 8, 29)


def test_download_end_is_exclusive_measurement_date() -> None:
    # yfinance's end date is exclusive, so Saturday includes Friday's completed bar.
    assert yahoo.default_download_end(date(2026, 8, 29)) == date(2026, 8, 29)


def test_corrupt_cache_is_not_silently_treated_as_empty(tmp_path) -> None:
    path = tmp_path / "prices.parquet"
    path.write_bytes(b"not a parquet file")

    with pytest.raises(Exception):
        cache.load_cache(path)


def test_validate_detects_duplicate_and_data_quality_issues() -> None:
    frame = make_long_frame(["AAA", "BBB"])
    frame.loc[0, "Close"] = 0
    frame.loc[1, "Volume"] = -1
    frame.loc[2, "Close"] = pd.NA
    frame = pd.concat([frame, frame.iloc[[3]]], ignore_index=True)

    report = validate_price_data(
        frame,
        requested_tickers=["AAA", "AAA", "BBB"],
        benchmark_tickers=["SPY"],
        minimum_history_days=5,
    )

    assert report.data_status is DataStatus.INCOMPLETE
    assert report.duplicate_tickers == ["AAA"]
    assert report.missing_tickers == []
    assert report.benchmark_missing_tickers == ["SPY"]
    assert report.non_positive_price_tickers == ["AAA"]
    assert report.negative_volume_tickers == ["AAA"]
    assert report.close_missing_tickers == ["AAA"]


def test_validate_detects_history_shortage() -> None:
    frame = make_long_frame(["AAA"], periods=2)

    report = validate_price_data(
        frame,
        requested_tickers=["AAA"],
        benchmark_tickers=["QQQ"],
        minimum_history_days=5,
    )

    assert report.data_status is DataStatus.INCOMPLETE
    assert report.history_short_tickers == ["AAA"]
    assert report.benchmark_missing_tickers == ["QQQ"]


def test_benchmark_uses_configured_proxy_when_index_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(tickers, start, end=None, chunk_size=75, timeout=30):
        tickers = list(tickers)
        if tickers == ["^SPX", "^NDX"]:
            return DownloadResult(
                data=pd.DataFrame(columns=["date", "ticker", *FIELDS]),
                requested_tickers=tickers,
                failures={ticker: "not available" for ticker in tickers},
            )
        return DownloadResult(
            data=make_long_frame(tickers),
            requested_tickers=tickers,
            successful_tickers=set(tickers),
        )

    monkeypatch.setattr(yahoo, "fetch_market_data", fake_fetch)
    result = yahoo.fetch_benchmarks(
        start=date(2024, 1, 1),
        specs=(
            BenchmarkSpec(name="sp500", index_ticker="^SPX", proxy_ticker="SPY"),
            BenchmarkSpec(name="nasdaq100", index_ticker="^NDX", proxy_ticker="QQQ"),
        ),
        minimum_history_days=5,
    )

    assert result.used_tickers == {"sp500": "SPY", "nasdaq100": "QQQ"}
    assert result.failures == {}
    assert result.fallback_reasons == {
        "sp500": "not available",
        "nasdaq100": "not available",
    }
