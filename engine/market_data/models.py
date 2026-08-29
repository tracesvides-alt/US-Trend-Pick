"""Models shared by the market-data download and cache pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


class DataStatus(StrEnum):
    """Whether all requested data passed the completeness checks."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class BenchmarkSpec(BaseModel):
    """Direct benchmark ticker and its configurable free-data proxy."""

    name: str
    index_ticker: str
    proxy_ticker: str
    allow_proxy: bool = True


DEFAULT_BENCHMARKS = (
    BenchmarkSpec(
        name="sp500",
        index_ticker="^GSPC",
        proxy_ticker="SPY",
    ),
    BenchmarkSpec(
        name="nasdaq100",
        index_ticker="^NDX",
        proxy_ticker="QQQ",
    ),
)


@dataclass
class DownloadResult:
    """Result of downloading one or more ticker chunks."""

    data: pd.DataFrame
    requested_tickers: list[str]
    successful_tickers: set[str] = field(default_factory=set)
    failures: dict[str, str] = field(default_factory=dict)
    duplicate_tickers: list[str] = field(default_factory=list)
    chunks: list[list[str]] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    """Downloaded benchmark data and the source selected for each benchmark."""

    data: pd.DataFrame
    used_tickers: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    fallback_reasons: dict[str, str] = field(default_factory=dict)


class ValidationReport(BaseModel):
    """Completeness and basic integrity results for a price-data snapshot."""

    data_status: DataStatus
    requested_tickers: int
    observed_tickers: int
    missing_tickers: list[str] = Field(default_factory=list)
    benchmark_missing_tickers: list[str] = Field(default_factory=list)
    duplicate_tickers: list[str] = Field(default_factory=list)
    close_missing_tickers: list[str] = Field(default_factory=list)
    volume_missing_tickers: list[str] = Field(default_factory=list)
    non_positive_price_tickers: list[str] = Field(default_factory=list)
    negative_volume_tickers: list[str] = Field(default_factory=list)
    history_short_tickers: list[str] = Field(default_factory=list)
    benchmark_history_short_tickers: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    minimum_history_days: int


class CacheMetadata(BaseModel):
    """JSON sidecar metadata written alongside the Parquet cache."""

    generated_at: datetime
    as_of: date
    data_status: DataStatus
    universe_count: int
    download_success: int
    failure_count: int
    failure_tickers: list[str] = Field(default_factory=list)
    history_shortage_count: int
    history_shortage_tickers: list[str] = Field(default_factory=list)
    cache_ticker_count: int
    cache_row_count: int
    cache_start: date | None = None
    cache_end: date | None = None
    download_start: date
    download_end: date
    benchmark_sources: dict[str, str] = Field(default_factory=dict)
    benchmark_failures: dict[str, str] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
