"""Time-aware Theme history loading and lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ThemeRecord:
    ticker: str
    theme: str
    effective_from: date
    effective_to: date | None = None


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date: {value}") from exc


def _records_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("themes", "history", "records"):
            value = payload.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                raise ValueError(f"theme_history.{key} must be a list")
            return value
    raise ValueError("theme_history.yaml must contain a list or themes/history/records list")


def load_theme_history(path: str | Path) -> list[ThemeRecord]:
    """Load the declared schema without applying future records."""

    theme_path = Path(path)
    if not theme_path.exists():
        return []
    payload = yaml.safe_load(theme_path.read_text(encoding="utf-8"))
    records: list[ThemeRecord] = []
    for index, row in enumerate(_records_payload(payload)):
        if not isinstance(row, dict):
            raise ValueError(f"theme_history record {index} must be a mapping")
        try:
            ticker = str(row["ticker"]).strip().upper()
            theme = str(row["theme"]).strip()
            effective_from = _parse_date(row["effective_from"], "effective_from")
            effective_to = (
                _parse_date(row["effective_to"], "effective_to")
                if row.get("effective_to") not in (None, "")
                else None
            )
        except KeyError as exc:
            raise ValueError(f"theme_history record {index} missing {exc.args[0]}") from exc
        if not ticker or not theme:
            raise ValueError(f"theme_history record {index} requires ticker and theme")
        if effective_to is not None and effective_to < effective_from:
            raise ValueError(f"theme_history record {index} effective_to precedes effective_from")
        records.append(ThemeRecord(ticker, theme, effective_from, effective_to))
    return records


def active_theme_map(records: list[ThemeRecord], as_of: date) -> dict[str, str]:
    """Return one active Theme per Ticker as of the measurement date."""

    active: dict[str, list[ThemeRecord]] = {}
    for record in records:
        if record.effective_from <= as_of and (
            record.effective_to is None or as_of <= record.effective_to
        ):
            active.setdefault(record.ticker, []).append(record)
    overlapping = {ticker: rows for ticker, rows in active.items() if len(rows) > 1}
    if overlapping:
        tickers = ", ".join(sorted(overlapping))
        raise ValueError(f"overlapping active Theme records: {tickers}")
    return {ticker: rows[0].theme for ticker, rows in active.items()}

