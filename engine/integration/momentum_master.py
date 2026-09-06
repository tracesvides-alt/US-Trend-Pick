"""Normalize Momentum Master cache files for the US Trend Pick frontend.

This adapter intentionally exports market-overview information only.  It does
not import Momentum Master's Streamlit application or reuse its ranking as a
US Trend Pick ranking input.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PERIODS = ("1d", "5d", "1mo", "3mo", "6mo", "YTD", "1y")


class MomentumRow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ticker: str = Field(min_length=1)
    name: str | None = None
    sector: str | None = None
    price: float | None = None
    return_value: float | None = Field(default=None, alias="return")
    signal: str | None = None
    rvol: float | None = None
    rsi: float | None = None


class MomentumRanking(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top: list[MomentumRow] = Field(default_factory=list)
    worst: list[MomentumRow] = Field(default_factory=list)


class IndexSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str
    emoji: str | None = None
    price: float | None = None
    returns: dict[str, float | None] = Field(default_factory=dict)
    error: bool = False


class MomentumSectorMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str | None = None
    price: float | None = None
    returns: dict[str, float | None] = Field(default_factory=dict)
    signal: str | None = None
    rvol: float | None = None
    rsi: float | None = None


class SectorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector: str
    count: int = Field(ge=0)
    returns: dict[str, float | None] = Field(default_factory=dict)
    members: list[MomentumSectorMember] = Field(default_factory=list)


class MomentumOverview(BaseModel):
    """Versioned, frontend-safe market overview artifact."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    as_of: str = Field(alias="asOf", min_length=10)
    price_as_of: str | None = Field(default=None, alias="priceAsOf")
    cache_updated_at: str | None = Field(default=None, alias="cacheUpdatedAt")
    generated_at: str = Field(alias="generatedAt", min_length=1)
    source: Literal["momentum_master"] = "momentum_master"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    periods: list[str]
    indices: list[IndexSnapshot]
    rankings: dict[str, MomentumRanking]
    sectors: list[SectorSnapshot]


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("Ticker", "")).strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            rows.append(row)
    return rows


def _extract_literal(source: Path, name: str) -> Any:
    if not source.exists():
        return {}
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return {}
    return {}


def _sector_map(source_dir: Path) -> dict[str, str]:
    """Read Momentum Master's static sector groups without importing its app."""

    source = source_dir / "market_logic.py"
    groups = _extract_literal(source, "SECTOR_DEFINITIONS")
    mapping: dict[str, str] = {}
    if isinstance(groups, dict):
        for sector, tickers in groups.items():
            if not isinstance(sector, str) or not isinstance(tickers, list):
                continue
            for ticker in tickers:
                if isinstance(ticker, str):
                    mapping.setdefault(ticker.upper(), sector)

    return mapping


def _thematic_etf_tickers(source_dir: Path) -> set[str]:
    values = _extract_literal(source_dir / "market_logic.py", "THEMATIC_ETFS")
    if not isinstance(values, dict):
        return set()
    return {ticker.upper() for ticker in values.values() if isinstance(ticker, str)}


def _cache_updated_at(source_dir: Path) -> str | None:
    marker = source_dir / "data" / "last_updated.txt"
    if not marker.exists():
        return None
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _history_snapshot(
    source_dir: Path,
) -> tuple[str | None, dict[str, dict[str, float]]]:
    """Read the cached price history and calculate exact trading-day returns.

    Momentum Master's CSV is retained as the fallback source, but its
    ``get_ret`` implementation indexes ``-5`` for a 5-day return, which is
    the fourth prior observation because ``-1`` is the current observation.
    The adapter corrects this at the integration boundary without changing
    the source repository.
    """

    path = source_dir / "data" / "history_cache.pkl"
    if not path.exists():
        return None, {}

    try:
        with path.open("rb") as handle:
            history = pickle.load(handle)
    except (OSError, EOFError, ImportError, ModuleNotFoundError, pickle.PickleError):
        return None, {}

    if not isinstance(history, dict):
        return None, {}

    latest_date: str | None = None
    corrected: dict[str, dict[str, float]] = {}
    windows = {"1d": 1, "5d": 5, "1mo": 21, "3mo": 63, "6mo": 126}

    for raw_ticker, frame in history.items():
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        try:
            close = frame["Close"].dropna()
            if len(close) == 0:
                continue
            dates = list(close.index)
            current_date = dates[-1]
            current_date_text = str(current_date)[:10]
            if len(current_date_text) == 10:
                latest_date = max(latest_date or current_date_text, current_date_text)
            current = float(close.iloc[-1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue

        values: dict[str, float] = {}
        for period, window in windows.items():
            if len(close) <= window:
                continue
            try:
                base = float(close.iloc[-window - 1])
                if not math.isfinite(base) or base == 0:
                    continue
                value = (current - base) / base * 100
                if math.isfinite(value):
                    values[period] = value
            except (IndexError, TypeError, ValueError):
                continue
        if values:
            corrected[ticker] = values

    return latest_date, corrected


def _apply_corrected_returns(
    rows: list[dict[str, Any]],
    corrected: dict[str, dict[str, float]],
) -> None:
    """Replace only return periods that can be recomputed from price history."""

    for row in rows:
        ticker = str(row.get("Ticker", "")).strip().upper()
        values = corrected.get(ticker)
        if not values:
            continue
        for period, value in values.items():
            row[period] = value


def _as_of(source_dir: Path, explicit: str | None, price_as_of: str | None) -> str:
    if explicit:
        return explicit[:10]
    if price_as_of and len(price_as_of) >= 10:
        return price_as_of[:10]
    updated = _cache_updated_at(source_dir)
    if updated and len(updated) >= 10:
        return updated[:10]
    return datetime.now(UTC).date().isoformat()


def _metadata_for(metadata: dict[str, Any], ticker: str) -> dict[str, Any]:
    value = metadata.get(ticker, {})
    return value if isinstance(value, dict) else {}


def _sector_for(
    ticker: str,
    metadata: dict[str, Any],
    sector_map: dict[str, str],
) -> str:
    if ticker in sector_map:
        return sector_map[ticker]
    entry = _metadata_for(metadata, ticker)
    for key in ("sector", "industry"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "未分類"


def _row_for_period(
    row: dict[str, Any],
    period: str,
    metadata: dict[str, Any],
    sector_map: dict[str, str],
) -> MomentumRow:
    ticker = str(row.get("Ticker", "")).strip().upper()
    entry = _metadata_for(metadata, ticker)
    name = entry.get("name")
    return MomentumRow(
        ticker=ticker,
        name=name if isinstance(name, str) and name.strip() else None,
        sector=_sector_for(ticker, metadata, sector_map),
        price=_float(row.get("Price")),
        return_value=_float(row.get(period)),
        signal=str(row.get("Signal", "")).strip() or None,
        rvol=_float(row.get("RVOL")),
        rsi=_float(row.get("RSI")),
    )


def _build_rankings(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    sector_map: dict[str, str],
    top_n: int,
) -> dict[str, MomentumRanking]:
    rankings: dict[str, MomentumRanking] = {}
    for period in PERIODS:
        valid = [
            row
            for row in rows
            if _float(row.get(period)) is not None
        ]
        descending = sorted(valid, key=lambda row: _float(row.get(period)) or 0.0, reverse=True)
        ascending = list(reversed(descending))
        rankings[period] = MomentumRanking(
            top=[_row_for_period(row, period, metadata, sector_map) for row in descending[:top_n]],
            worst=[_row_for_period(row, period, metadata, sector_map) for row in ascending[:top_n]],
        )
    return rankings


def _sector_member_for(
    row: dict[str, Any],
    metadata: dict[str, Any],
) -> MomentumSectorMember:
    ticker = str(row.get("Ticker", "")).strip().upper()
    entry = _metadata_for(metadata, ticker)
    name = entry.get("name")
    return MomentumSectorMember(
        ticker=ticker,
        name=name if isinstance(name, str) and name.strip() else None,
        price=_float(row.get("Price")),
        returns={period: _float(row.get(period)) for period in PERIODS},
        signal=str(row.get("Signal", "")).strip() or None,
        rvol=_float(row.get("RVOL")),
        rsi=_float(row.get("RSI")),
    )


def _build_sectors(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    sector_map: dict[str, str],
    excluded_tickers: set[str],
) -> list[SectorSnapshot]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = str(row.get("Ticker", "")).strip().upper()
        if ticker and ticker not in excluded_tickers:
            grouped.setdefault(_sector_for(ticker, metadata, sector_map), []).append(row)

    sectors: list[SectorSnapshot] = []
    for sector, sector_rows in grouped.items():
        returns: dict[str, float | None] = {}
        for period in PERIODS:
            values = [_float(row.get(period)) for row in sector_rows]
            values = [value for value in values if value is not None]
            returns[period] = sum(values) / len(values) if values else None
        members = [
            _sector_member_for(row, metadata)
            for row in sorted(sector_rows, key=lambda item: str(item.get("Ticker", "")).upper())
        ]
        sectors.append(
            SectorSnapshot(
                sector=sector,
                count=len(sector_rows),
                returns=returns,
                members=members,
            )
        )
    return sorted(sectors, key=lambda item: item.sector)


def _build_indices(path: Path) -> list[IndexSnapshot]:
    payload = _read_json(path, {})
    if not isinstance(payload, dict):
        return []
    indices: list[IndexSnapshot] = []
    for ticker, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        raw_returns = raw.get("returns", {})
        returns = {
            period: _float(raw_returns.get(period)) if isinstance(raw_returns, dict) else None
            for period in PERIODS
        }
        indices.append(
            IndexSnapshot(
                ticker=str(ticker),
                name=str(raw.get("name", ticker)),
                emoji=str(raw.get("emoji", "")) or None,
                price=_float(raw.get("price")),
                returns=returns,
                error=bool(raw.get("error", False)),
            )
        )
    return indices


def build_overview(
    source_dir: str | Path,
    *,
    as_of: str | None = None,
    top_n: int = 10,
) -> MomentumOverview:
    """Build a validated overview from a checked-out Momentum Master repo."""

    root = Path(source_dir)
    rows = _load_rows(root / "data" / "momentum_cache.csv")
    metadata = _read_json(root / "data" / "metadata_cache.json", {})
    if not isinstance(metadata, dict):
        metadata = {}
    sector_map = _sector_map(root)
    excluded_tickers = _thematic_etf_tickers(root)
    indices = _build_indices(root / "data" / "indices_cache.json")
    price_as_of, corrected_returns = _history_snapshot(root)
    _apply_corrected_returns(rows, corrected_returns)
    cache_updated_at = _cache_updated_at(root)
    generated_at = datetime.now(UTC).isoformat()
    status: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE" if rows else "UNAVAILABLE"
    return MomentumOverview(
        asOf=_as_of(root, as_of, price_as_of),
        priceAsOf=price_as_of,
        cacheUpdatedAt=cache_updated_at,
        generatedAt=generated_at,
        source="momentum_master",
        status=status,
        periods=list(PERIODS),
        indices=indices,
        rankings=_build_rankings(rows, metadata, sector_map, max(1, top_n)),
        sectors=_build_sectors(rows, metadata, sector_map, excluded_tickers),
    )


def write_overview(document: MomentumOverview, output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Momentum Master overview JSON")
    parser.add_argument("--source-dir", required=True, help="Checked-out Momentum Master root")
    parser.add_argument(
        "--output",
        default="web/public/data/momentum-overview.json",
        help="Frontend JSON output path",
    )
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()
    document = build_overview(args.source_dir, as_of=args.as_of, top_n=args.top_n)
    write_overview(document, args.output)
    print(f"Momentum overview: {document.status}")
    print(f"As Of: {document.as_of}")
    print(f"Rows: {sum(len(group.top) for group in document.rankings.values())}")
    print(f"Sectors: {len(document.sectors)}")


if __name__ == "__main__":
    main()
