"""Time-aware Primary Theme catalog and history loading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THEME_CATALOG_PATH = PROJECT_ROOT / "config" / "themes.yaml"


@dataclass(frozen=True)
class ThemeDefinition:
    """One canonical Primary Theme from the master catalog."""

    name: str
    description: str | None = None


@dataclass(frozen=True)
class ThemeRecord:
    ticker: str
    theme: str
    effective_from: date
    effective_to: date | None = None
    note: str | None = None


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date: {value}") from exc


def _records_payload(payload: Any, filename: str) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get("themes", payload.get("history", payload.get("records")))
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{filename} themes/history/records must be a list")
        return value
    raise ValueError(f"{filename} must contain a list or themes/history/records list")


def load_theme_catalog(
    path: str | Path = DEFAULT_THEME_CATALOG_PATH,
) -> dict[str, ThemeDefinition]:
    """Load the canonical Primary Theme catalog keyed case-insensitively."""

    theme_path = Path(path)
    if not theme_path.exists():
        return {}
    payload = yaml.safe_load(theme_path.read_text(encoding="utf-8"))
    catalog: dict[str, ThemeDefinition] = {}
    for index, row in enumerate(_records_payload(payload, "themes.yaml")):
        if isinstance(row, str):
            name = row.strip()
            description = None
        elif isinstance(row, dict):
            name = str(row.get("name", "")).strip()
            description_value = row.get("description")
            description = (
                str(description_value).strip()
                if description_value not in (None, "")
                else None
            )
        else:
            raise ValueError(f"themes.yaml record {index} must be a string or mapping")
        if not name:
            raise ValueError(f"themes.yaml record {index} requires name")
        key = name.casefold()
        if key in catalog:
            raise ValueError(f"duplicate Primary Theme in themes.yaml: {name}")
        catalog[key] = ThemeDefinition(name=name, description=description)
    return catalog


def _canonical_theme(
    value: Any,
    catalog: dict[str, ThemeDefinition],
) -> str:
    theme = str(value).strip()
    definition = catalog.get(theme.casefold())
    if definition is None:
        raise ValueError(f"theme_history uses undefined Primary Theme: {theme}")
    return definition.name


def load_theme_history(
    path: str | Path,
    catalog_path: str | Path = DEFAULT_THEME_CATALOG_PATH,
) -> list[ThemeRecord]:
    """Load history and reject every Theme missing from the master catalog."""

    catalog = load_theme_catalog(catalog_path)
    theme_path = Path(path)
    if not theme_path.exists():
        return []
    payload = yaml.safe_load(theme_path.read_text(encoding="utf-8"))
    records: list[ThemeRecord] = []
    for index, row in enumerate(_records_payload(payload, "theme_history.yaml")):
        if not isinstance(row, dict):
            raise ValueError(f"theme_history record {index} must be a mapping")
        try:
            ticker = str(row["ticker"]).strip().upper()
            theme = _canonical_theme(row["theme"], catalog)
            effective_from = _parse_date(row["effective_from"], "effective_from")
            effective_to = (
                _parse_date(row["effective_to"], "effective_to")
                if row.get("effective_to") not in (None, "")
                else None
            )
        except KeyError as exc:
            raise ValueError(f"theme_history record {index} missing {exc.args[0]}") from exc
        note_value = row.get("note")
        note = str(note_value).strip() if note_value not in (None, "") else None
        if not ticker or not theme:
            raise ValueError(f"theme_history record {index} requires ticker and theme")
        if effective_to is not None and effective_to < effective_from:
            raise ValueError(f"theme_history record {index} effective_to precedes effective_from")
        records.append(ThemeRecord(ticker, theme, effective_from, effective_to, note))
    return records


def active_theme_map(records: list[ThemeRecord], as_of: date) -> dict[str, str]:
    """Return one canonical active Primary Theme per ticker as of the date."""

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
