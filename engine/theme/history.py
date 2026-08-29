"""Point-in-time Theme snapshots and automatically maintained history."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from engine.theme.models import (
    ThemeChangeRecord,
    ThemeClassification,
    ThemeHistoryRecord,
    ThemeRunResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THEME_DIR = PROJECT_ROOT / "data" / "themes"
DEFAULT_HISTORY_PATH = DEFAULT_THEME_DIR / "history.json"
DEFAULT_CHANGE_PATH = DEFAULT_THEME_DIR / "theme-changes.json"
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _list_payload(payload: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get(label, payload.get("records", []))
    if payload is None:
        return []
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"{label} must contain a list of objects")
    return payload


def load_theme_history(
    path: str | Path = DEFAULT_HISTORY_PATH,
) -> list[ThemeHistoryRecord]:
    """Load automatically generated Theme validity intervals."""

    history_path = Path(path)
    if not history_path.exists():
        return []
    payload = json.loads(history_path.read_text(encoding="utf-8"))
    return [ThemeHistoryRecord.model_validate(row) for row in _list_payload(payload, "history")]


def load_theme_snapshot(path: str | Path) -> list[ThemeClassification]:
    """Load one point-in-time Theme snapshot."""

    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return []
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return [
        ThemeClassification.model_validate(row)
        for row in _list_payload(payload, "classifications")
    ]


def _dated_files(theme_dir: str | Path, as_of: date | None = None) -> list[Path]:
    files: list[tuple[date, Path]] = []
    for path in Path(theme_dir).glob("*.json"):
        match = _DATE_RE.match(path.stem)
        if not match:
            continue
        snapshot_date = date.fromisoformat(match.group(1))
        if as_of is None or snapshot_date <= as_of:
            files.append((snapshot_date, path))
    return [path for _, path in sorted(files)]


def latest_theme_snapshot_map(
    theme_dir: str | Path = DEFAULT_THEME_DIR,
    before: date | None = None,
) -> dict[str, ThemeClassification]:
    """Return the latest snapshot row for each ticker before a run."""

    latest: dict[str, ThemeClassification] = {}
    for path in _dated_files(theme_dir, before):
        for row in load_theme_snapshot(path):
            if before is not None and row.as_of >= before:
                continue
            latest[row.ticker] = row
    return latest


def active_theme_history_map(
    records: Iterable[ThemeHistoryRecord],
    as_of: date,
) -> dict[str, ThemeHistoryRecord]:
    """Return one active history record per ticker and reject overlaps."""

    active: dict[str, list[ThemeHistoryRecord]] = {}
    for record in records:
        if record.effective_from <= as_of and (
            record.effective_to is None or as_of <= record.effective_to
        ):
            active.setdefault(record.ticker, []).append(record)
    overlapping = {ticker: rows for ticker, rows in active.items() if len(rows) > 1}
    if overlapping:
        tickers = ", ".join(sorted(overlapping))
        raise ValueError(f"overlapping automatic Theme history records: {tickers}")
    return {ticker: rows[0] for ticker, rows in active.items()}


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _ordered_scores(row: ThemeClassification) -> list[tuple[str, float]]:
    scores = {
        str(theme): float(score)
        for theme, score in row.theme_scores.items()
        if _finite(score)
    }
    if not scores:
        scores = {
            row.primary_theme: float(row.theme_score),
            row.second_theme: float(row.second_theme_score),
        }
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _with_stable_theme(
    row: ThemeClassification,
    current: ThemeHistoryRecord | None,
    prior: ThemeClassification | None,
    as_of: date,
) -> ThemeClassification:
    proposed = row.proposed_theme or row.primary_theme
    current_theme = current.primary_theme if current else None
    changed = False
    reason: str | None = None
    if current_theme is None:
        final_theme = proposed
        reason = "INITIAL_CLASSIFICATION"
    elif proposed == current_theme:
        final_theme = current_theme
    elif (
        prior is not None
        and prior.as_of < as_of
        and prior.proposed_theme == proposed
        and prior.primary_theme == current_theme
    ):
        final_theme = proposed
        changed = True
        reason = "TWO_CONSECUTIVE_WEEKLY_WINS"
    else:
        final_theme = current_theme
        reason = "STABILITY_HOLD"

    ordered = _ordered_scores(row)
    score_map = dict(ordered)
    final_score = score_map.get(final_theme, 0.0)
    second = next(
        ((theme, score) for theme, score in ordered if theme != final_theme),
        ("Other", 0.0),
    )
    return row.model_copy(
        update={
            "primary_theme": final_theme,
            "theme_score": max(0.0, min(100.0, final_score)),
            "second_theme": second[0],
            "second_theme_score": max(0.0, min(100.0, second[1])),
            "previous_theme": current_theme,
            "theme_changed": changed,
            "change_reason": reason,
            "as_of": as_of,
        }
    )


def stabilize_classifications(
    classifications: Iterable[ThemeClassification],
    history: Iterable[ThemeHistoryRecord],
    prior_snapshots: dict[str, ThemeClassification],
    as_of: date,
) -> list[ThemeClassification]:
    """Apply the two-consecutive-snapshot Theme change rule."""

    records = list(history)
    active = active_theme_history_map(records, as_of)
    return [
        _with_stable_theme(
            row,
            active.get(row.ticker),
            prior_snapshots.get(row.ticker),
            as_of,
        )
        for row in classifications
    ]


def update_theme_history(
    history: Iterable[ThemeHistoryRecord],
    classifications: Iterable[ThemeClassification],
    as_of: date,
) -> tuple[list[ThemeHistoryRecord], list[ThemeChangeRecord]]:
    """Append/close validity intervals without overwriting prior history."""

    records = list(history)
    changes: list[ThemeChangeRecord] = []
    active = active_theme_history_map(records, as_of)
    close_date = as_of - timedelta(days=1)

    for row in classifications:
        current = active.get(row.ticker)
        if current is not None and current.primary_theme == row.primary_theme:
            continue
        if current is not None and current.primary_theme != row.primary_theme:
            records = [
                record.model_copy(update={"effective_to": close_date})
                if record.ticker == row.ticker
                and record.effective_from == current.effective_from
                else record
                for record in records
            ]
            changes.append(
                ThemeChangeRecord(
                    ticker=row.ticker,
                    previous_theme=current.primary_theme,
                    new_theme=row.primary_theme,
                    as_of=as_of,
                    reason=row.change_reason or "AUTOMATIC_CLASSIFIER_CHANGE",
                )
            )
        records.append(
            ThemeHistoryRecord(
                ticker=row.ticker,
                primary_theme=row.primary_theme,
                effective_from=as_of,
            )
        )
        active[row.ticker] = records[-1]

    deduped: dict[tuple[str, date], ThemeHistoryRecord] = {}
    for record in records:
        deduped[(record.ticker, record.effective_from)] = record
    result = sorted(deduped.values(), key=lambda item: (item.ticker, item.effective_from))
    return result, changes


def load_theme_changes(
    path: str | Path = DEFAULT_CHANGE_PATH,
) -> list[ThemeChangeRecord]:
    """Load the aggregate Theme change log."""

    change_path = Path(path)
    if not change_path.exists():
        return []
    payload = json.loads(change_path.read_text(encoding="utf-8"))
    return [
        ThemeChangeRecord.model_validate(row)
        for row in _list_payload(payload, "changes")
    ]


def write_theme_artifacts(
    result: ThemeRunResult,
    theme_dir: str | Path = DEFAULT_THEME_DIR,
) -> dict[str, Path]:
    """Persist the point-in-time snapshot, history, and change log."""

    directory = Path(theme_dir)
    snapshot_path = directory / f"{result.as_of.isoformat()}.json"
    history_path = directory / "history.json"
    change_path = directory / "theme-changes.json"
    _atomic_write(
        snapshot_path,
        [row.model_dump(mode="json") for row in result.classifications],
    )
    _atomic_write(history_path, [row.model_dump(mode="json") for row in result.history])

    existing = load_theme_changes(change_path)
    keyed = {
        (row.ticker, row.as_of, row.previous_theme, row.new_theme): row
        for row in existing
    }
    for row in result.changes:
        keyed[(row.ticker, row.as_of, row.previous_theme, row.new_theme)] = row
    merged_changes = sorted(
        keyed.values(), key=lambda row: (row.as_of, row.ticker)
    )
    _atomic_write(change_path, [row.model_dump(mode="json") for row in merged_changes])
    return {
        "snapshot": snapshot_path,
        "history": history_path,
        "changes": change_path,
    }
