"""Deterministic offline price fixture for the Base Ranking golden test."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_golden_inputs() -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    """Return fixed 300-session data with an unambiguous A/B/C ordering."""

    dates = pd.bdate_range("2025-01-02", periods=300)
    index = np.arange(len(dates), dtype=float)

    def rows(ticker: str, adjusted: np.ndarray, volume: np.ndarray) -> pd.DataFrame:
        close = 100.0 + index * 0.01
        return pd.DataFrame(
            {
                "date": dates,
                "ticker": ticker,
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Adj Close": adjusted,
                "Volume": volume,
            }
        )

    benchmark = rows(
        "SPY",
        100.0 + index * 0.05,
        np.full(len(index), 1_000_000.0),
    )
    prices = pd.concat(
        [
            rows("AAA", 100.0 + index * 0.50, 1_000.0 + index * 10.0),
            rows("BBB", 100.0 + index * 0.10, np.full(len(index), 1_000.0)),
            rows("CCC", 150.0 - index * 0.10, 4_000.0 - index * 5.0),
        ],
        ignore_index=True,
    )
    return ["AAA", "BBB", "CCC"], pd.concat([prices, benchmark], ignore_index=True), benchmark
