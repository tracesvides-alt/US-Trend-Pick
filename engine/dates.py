"""Measurement-date helpers shared by scheduled batch jobs."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MEASUREMENT_TIMEZONE = ZoneInfo("Asia/Tokyo")


def measurement_date(now: datetime | None = None) -> date:
    """Return the measurement date in the application's fixed JST timezone."""

    current = now if now is not None else datetime.now(MEASUREMENT_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MEASUREMENT_TIMEZONE)
    return current.astimezone(MEASUREMENT_TIMEZONE).date()


def measurement_now() -> datetime:
    """Return an aware timestamp in the application's fixed JST timezone."""

    return datetime.now(MEASUREMENT_TIMEZONE)
