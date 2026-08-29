"""Return and relative-strength helpers used by Tactical Ranking."""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.ranking.momentum import adjusted_price_series


def calculate_period_return(
    data: pd.DataFrame | pd.Series,
    periods: int,
) -> float:
    """Calculate an adjusted-price return over trading observations."""

    if periods <= 0:
        raise ValueError("periods must be greater than zero")
    prices = adjusted_price_series(data)
    if len(prices) <= periods:
        return float("nan")
    start = prices.iloc[-1 - periods]
    end = prices.iloc[-1]
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return float("nan")
    return float(end / start - 1.0)


def calculate_relative_20d_return(
    stock_data: pd.DataFrame | pd.Series,
    benchmark_data: pd.DataFrame | pd.Series,
    periods: int = 20,
) -> float:
    """Return stock 20D return minus S&P500 20D return."""

    stock_return = calculate_period_return(stock_data, periods)
    benchmark_return = calculate_period_return(benchmark_data, periods)
    if not np.isfinite(stock_return) or not np.isfinite(benchmark_return):
        return float("nan")
    return float(stock_return - benchmark_return)


def calculate_rs_drawdown(
    stock_data: pd.DataFrame | pd.Series,
    benchmark_data: pd.DataFrame | pd.Series,
    lookback: int = 63,
) -> float:
    """Calculate current RS drawdown from the prior lookback maximum.

    Relative strength is the aligned adjusted-price ratio. The current
    observation is excluded from the lookback maximum so the result is a true
    drawdown from prior leadership rather than always being zero.
    """

    if lookback <= 0:
        raise ValueError("lookback must be greater than zero")
    stock = adjusted_price_series(stock_data).rename("stock")
    benchmark = adjusted_price_series(benchmark_data).rename("benchmark")
    aligned = pd.concat([stock, benchmark], axis=1, join="inner").dropna()
    if len(aligned) <= lookback:
        return float("nan")
    if (aligned["benchmark"] <= 0).any() or (aligned["stock"] <= 0).any():
        return float("nan")
    relative_strength = aligned["stock"] / aligned["benchmark"]
    prior = relative_strength.iloc[-lookback - 1 : -1]
    prior_max = prior.max()
    current = relative_strength.iloc[-1]
    if not np.isfinite(prior_max) or prior_max <= 0 or not np.isfinite(current):
        return float("nan")
    return float(current / prior_max - 1.0)


def _price_before(prices: pd.Series, boundary: pd.Timestamp) -> float | None:
    prior = prices.loc[prices.index < boundary]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def calculate_ytd_return(data: pd.DataFrame | pd.Series) -> float:
    """Calculate return from the last available price before the current year."""

    prices = adjusted_price_series(data)
    if prices.empty:
        return float("nan")
    latest_date = prices.index[-1]
    boundary = pd.Timestamp(year=latest_date.year, month=1, day=1)
    start = _price_before(prices, boundary)
    if start is None:
        return float("nan")
    end = float(prices.iloc[-1])
    return float(end / start - 1.0) if start > 0 else float("nan")


def calculate_mtd_return(data: pd.DataFrame | pd.Series) -> float:
    """Calculate return from the last available price before the current month."""

    prices = adjusted_price_series(data)
    if prices.empty:
        return float("nan")
    latest_date = prices.index[-1]
    boundary = pd.Timestamp(year=latest_date.year, month=latest_date.month, day=1)
    start = _price_before(prices, boundary)
    if start is None:
        return float("nan")
    end = float(prices.iloc[-1])
    return float(end / start - 1.0) if start > 0 else float("nan")


def calculate_weekly_return(data: pd.DataFrame | pd.Series, periods: int = 5) -> float:
    """Calculate the adjusted-price return over one trading week."""

    return calculate_period_return(data, periods)


def calculate_display_returns(data: pd.DataFrame | pd.Series) -> dict[str, float]:
    """Return the YTD, MTD, and weekly display metrics."""

    return {
        "ytd": calculate_ytd_return(data),
        "mtd": calculate_mtd_return(data),
        "weekly": calculate_weekly_return(data),
    }

