"""Dollar-volume expansion calculation."""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_RECENT_DAYS = 63
DEFAULT_PRIOR_DAYS = 189


def calculate_dollar_volume_expansion(
    data: pd.DataFrame,
    recent_days: int = DEFAULT_RECENT_DAYS,
    prior_days: int = DEFAULT_PRIOR_DAYS,
) -> float:
    """Calculate recent mean raw dollar volume divided by prior mean."""

    if recent_days <= 0 or prior_days <= 0:
        raise ValueError("recent_days and prior_days must be greater than zero")
    if not {"Close", "Volume"}.issubset(data.columns):
        return float("nan")
    frame = data[["Close", "Volume"]].copy()
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce")
    if (frame["Close"].dropna() <= 0).any() or (frame["Volume"].dropna() < 0).any():
        return float("nan")
    dollar_volume = (frame["Close"] * frame["Volume"]).dropna()
    required = recent_days + prior_days
    if len(dollar_volume) < required:
        return float("nan")
    recent = dollar_volume.iloc[-recent_days:]
    prior = dollar_volume.iloc[-required:-recent_days]
    recent_mean = float(recent.mean())
    prior_mean = float(prior.mean())
    if not np.isfinite(recent_mean) or not np.isfinite(prior_mean) or prior_mean <= 0:
        return float("nan")
    return recent_mean / prior_mean
