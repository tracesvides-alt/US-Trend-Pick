from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.ranking.regime import (
    RegimeState,
    calculate_breadth,
    calculate_market_regime_score,
    calculate_trend,
    classify_regime,
    calculate_volatility,
    strategy_leadership_score,
    volatility_score,
)


def test_trend_score_and_stage4_use_strict_conditions() -> None:
    up = pd.Series(
        np.linspace(100.0, 200.0, 250),
        index=pd.date_range("2024-01-01", periods=250, freq="B"),
    )
    down = pd.Series(
        np.linspace(200.0, 100.0, 250),
        index=pd.date_range("2024-01-01", periods=250, freq="B"),
    )

    up_metrics = calculate_trend(up)
    down_metrics = calculate_trend(down)

    assert up_metrics.score == 100.0
    assert up_metrics.stage4 is False
    assert down_metrics.score == 0.0
    assert down_metrics.stage4 is True


def test_breadth_is_equal_weighted_across_three_universes() -> None:
    universe = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "source_spy": [True, True, True],
            "source_qqq": [True, True, False],
            "source_qqqj": [False, True, True],
        }
    )
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    price_data = pd.concat(
        [
            pd.DataFrame({"date": dates, "ticker": "A", "Adj Close": [1.0, 2.0, 3.0]}),
            pd.DataFrame({"date": dates, "ticker": "B", "Adj Close": [3.0, 2.0, 1.0]}),
            pd.DataFrame({"date": dates, "ticker": "C", "Adj Close": [1.0, 1.0, 2.0]}),
        ],
        ignore_index=True,
    )

    result = calculate_breadth(universe, price_data, dma_window=2)

    assert result.ratios == {"sp500": 2 / 3, "nasdaq100": 0.5, "next100": 0.5}
    assert result.score == pytest.approx(100 * (2 / 3 + 0.5 + 0.5) / 3)


def test_strategy_leadership_score_mapping_boundaries() -> None:
    assert strategy_leadership_score(-0.08) == 0.0
    assert strategy_leadership_score(-0.03) == 30.0
    assert strategy_leadership_score(0.0) == 60.0
    assert strategy_leadership_score(0.02) == 80.0
    assert strategy_leadership_score(0.05) == 100.0
    assert strategy_leadership_score(0.01) == 70.0


def test_volatility_score_mapping_boundaries_and_clipping() -> None:
    assert volatility_score(0.8) == 100.0
    assert volatility_score(1.0) == 90.0
    assert volatility_score(1.25) == 70.0
    assert volatility_score(1.5) == 50.0
    assert volatility_score(1.75) == 25.0
    assert volatility_score(2.0) == 0.0
    assert volatility_score(2.5) == 0.0


def test_volatility_baseline_excludes_current_realized_volatility() -> None:
    prices = pd.Series(
        [100.0, 101.0, 100.0, 102.0, 99.0, 103.0, 98.0, 104.0, 97.0, 105.0],
        index=pd.date_range("2024-01-01", periods=10, freq="B"),
    )
    returns = prices.pct_change(fill_method=None)
    realized = returns.rolling(2).std(ddof=1) * np.sqrt(252.0)
    valid = realized.dropna()

    metrics = calculate_volatility(prices, realized_window=2, history_window=3)

    assert metrics.status == "OK"
    assert metrics.current_20d_realized_vol == pytest.approx(valid.iloc[-1])
    assert metrics.historical_median_20d_realized_vol == pytest.approx(
        valid.iloc[-4:-1].median()
    )
    assert metrics.ratio == pytest.approx(valid.iloc[-1] / valid.iloc[-4:-1].median())


def test_regime_score_uses_20_15_25_20_20_weights() -> None:
    scores = {
        "nasdaq100_trend": 100.0,
        "sp500_trend": 80.0,
        "market_breadth": 60.0,
        "strategy_leadership": 40.0,
        "volatility_regime": 20.0,
    }

    assert calculate_market_regime_score(scores) == 59.0


def test_regime_threshold_boundaries_without_previous_state() -> None:
    assert classify_regime(70.0) == RegimeState.RISK_ON
    assert classify_regime(69.0) == RegimeState.WARNING
    assert classify_regime(41.0) == RegimeState.WARNING
    assert classify_regime(40.0) == RegimeState.RISK_OFF


def test_regime_hysteresis_boundaries() -> None:
    assert classify_regime(70.0, RegimeState.WARNING) == RegimeState.RISK_ON
    assert classify_regime(40.0, RegimeState.WARNING) == RegimeState.RISK_OFF
    assert classify_regime(69.0, RegimeState.WARNING) == RegimeState.WARNING
    assert classify_regime(60.0, RegimeState.RISK_ON) == RegimeState.RISK_ON
    assert classify_regime(59.99, RegimeState.RISK_ON) == RegimeState.WARNING
    assert classify_regime(50.0, RegimeState.RISK_OFF) == RegimeState.WARNING
    assert classify_regime(49.99, RegimeState.RISK_OFF) == RegimeState.RISK_OFF


def test_stage_override_forbids_on_and_can_force_off() -> None:
    assert (
        classify_regime(90.0, nasdaq_stage4=True)
        == RegimeState.WARNING
    )
    assert (
        classify_regime(90.0, nasdaq_stage4=True, sp500_stage4=True)
        == RegimeState.RISK_OFF
    )
