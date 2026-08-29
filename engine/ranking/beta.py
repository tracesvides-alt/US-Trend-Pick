"""Weekly-return beta calculation and maturity adjustment."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.ranking.momentum import adjusted_price_series

MINIMUM_BETA_MONTHS = 12
NEUTRAL_BETA_MIN_MONTHS = 12
FULL_24M_MIN_MONTHS = 24
FULL_60M_MIN_MONTHS = 60


@dataclass(frozen=True)
class BetaMetrics:
    """Effective beta and its maturity status for one asset."""

    beta_raw: float | None
    months: int
    status: str
    beta_score: float | None = None


def shrink_beta(raw_beta: float, months: int) -> float:
    """Shrink beta one-directionally toward one for shorter histories."""

    if months < 0:
        raise ValueError("months must be non-negative")
    return float(1.0 + np.sqrt(months / 60.0) * (raw_beta - 1.0))


def _weekly_prices(data: pd.DataFrame | pd.Series) -> pd.Series:
    prices = adjusted_price_series(data)
    if prices.empty:
        return prices
    return prices.resample("W-FRI").last().dropna()


def _calendar_months(start: pd.Timestamp, end: pd.Timestamp) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _weekly_returns(
    asset_prices: pd.Series,
    benchmark_prices: pd.Series,
) -> tuple[pd.DataFrame, int]:
    prices = pd.concat(
        [asset_prices.rename("asset"), benchmark_prices.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if prices.empty:
        return pd.DataFrame(columns=["asset", "benchmark"]), 0
    months = _calendar_months(prices.index.min(), prices.index.max())
    returns = prices.pct_change(fill_method=None).dropna()
    return returns, months


def _beta_from_returns(returns: pd.DataFrame) -> float | None:
    if len(returns) < 2:
        return None
    benchmark_variance = returns["benchmark"].var(ddof=1)
    if not np.isfinite(benchmark_variance) or benchmark_variance <= 0:
        return None
    covariance = returns["asset"].cov(returns["benchmark"])
    if not np.isfinite(covariance):
        return None
    return float(covariance / benchmark_variance)


def _beta_for_months(returns: pd.DataFrame, end: pd.Timestamp, months: int) -> float | None:
    start = end - pd.DateOffset(months=months)
    window = returns.loc[returns.index > start]
    return _beta_from_returns(window)


def calculate_beta(
    asset_data: pd.DataFrame | pd.Series,
    benchmark_data: pd.DataFrame | pd.Series,
) -> BetaMetrics:
    """Calculate effective beta using aligned weekly adjusted-price returns."""

    asset_prices = _weekly_prices(asset_data)
    benchmark_prices = _weekly_prices(benchmark_data)
    returns, months = _weekly_returns(asset_prices, benchmark_prices)
    if months < MINIMUM_BETA_MONTHS:
        return BetaMetrics(None, months, "HISTORY_LT_12M")

    available_beta = _beta_from_returns(returns)
    if available_beta is None:
        return BetaMetrics(None, months, "BETA_UNAVAILABLE")
    if months < FULL_24M_MIN_MONTHS:
        effective = shrink_beta(available_beta, months)
        return BetaMetrics(effective, months, "NEUTRAL_12_23M", beta_score=50.0)

    beta_24 = _beta_for_months(returns, returns.index.max(), 24)
    if beta_24 is None:
        return BetaMetrics(None, months, "BETA_24M_UNAVAILABLE")
    if months < FULL_60M_MIN_MONTHS:
        blended = beta_24 * 0.60 + available_beta * 0.40
    else:
        beta_60 = _beta_for_months(returns, returns.index.max(), 60)
        if beta_60 is None:
            return BetaMetrics(None, months, "BETA_60M_UNAVAILABLE")
        blended = beta_24 * 0.60 + beta_60 * 0.40
    return BetaMetrics(shrink_beta(blended, months), months, "OK")

