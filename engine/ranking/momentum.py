"""Adjusted-price 12-1M momentum calculation."""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_MOMENTUM_LOOKBACK_DAYS = 252
DEFAULT_MOMENTUM_SKIP_DAYS = 21


def adjusted_price_series(
    data: pd.DataFrame | pd.Series,
    column: str = "Adj Close",
) -> pd.Series:
    """Return a sorted, deduplicated adjusted-price series."""

    if isinstance(data, pd.Series):
        series = data.copy()
    else:
        if column not in data.columns:
            return pd.Series(dtype="float64")
        frame = data.copy()
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date"]).set_index("date")
        series = frame[column]
    series.index = pd.to_datetime(series.index, errors="coerce", utc=True)
    series.index = series.index.tz_convert(None).normalize()
    series = pd.to_numeric(series, errors="coerce")
    series = series[~series.index.isna()].dropna()
    return series[~series.index.duplicated(keep="last")].sort_index()


def calculate_momentum(
    data: pd.DataFrame | pd.Series,
    lookback_days: int = DEFAULT_MOMENTUM_LOOKBACK_DAYS,
    skip_days: int = DEFAULT_MOMENTUM_SKIP_DAYS,
) -> float:
    """Calculate 12-1M momentum from adjusted prices.

    The numerator is the price ``skip_days`` before the latest observation,
    so the latest 21 observations cannot affect the result. The denominator
    is ``lookback_days`` observations before the latest observation.
    """

    if lookback_days <= skip_days or skip_days < 0:
        raise ValueError("lookback_days must be greater than non-negative skip_days")
    prices = adjusted_price_series(data)
    if len(prices) <= lookback_days:
        return float("nan")
    numerator = prices.iloc[-1 - skip_days]
    denominator = prices.iloc[-1 - lookback_days]
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator <= 0:
        return float("nan")
    return float(numerator / denominator - 1.0)
