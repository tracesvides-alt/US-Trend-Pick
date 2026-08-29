"""Price-stage and New Buy rules for Tactical Ranking."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.ranking.momentum import adjusted_price_series


@dataclass(frozen=True)
class StageMetrics:
    stage: str
    stage4: bool
    price: float | None
    dma50: float | None
    dma200: float | None
    status: str


def calculate_stage(
    data: pd.DataFrame | pd.Series,
    dma50_window: int = 50,
    dma200_window: int = 200,
) -> StageMetrics:
    """Calculate Stage 4 using strict price and moving-average conditions."""

    prices = adjusted_price_series(data)
    if len(prices) < dma200_window:
        return StageMetrics("Unknown", False, None, None, None, "INSUFFICIENT_HISTORY")
    dma50 = prices.rolling(dma50_window).mean().iloc[-1]
    dma200 = prices.rolling(dma200_window).mean().iloc[-1]
    price = float(prices.iloc[-1])
    if not np.isfinite(dma50) or not np.isfinite(dma200) or not np.isfinite(price):
        return StageMetrics("Unknown", False, price, None, None, "INSUFFICIENT_HISTORY")
    stage4 = bool(price < dma200 and dma50 < dma200)
    return StageMetrics(
        "Stage4" if stage4 else "Normal",
        stage4,
        price,
        float(dma50),
        float(dma200),
        "OK",
    )


def calculate_new_buy(stage4: bool, health: float) -> bool:
    """Allow New Buy only outside Stage 4 and at Health >= 35."""

    return bool(not stage4 and np.isfinite(health) and health >= 35.0)
