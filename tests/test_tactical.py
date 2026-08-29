from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.ranking.returns import (
    calculate_display_returns,
    calculate_relative_20d_return,
    calculate_rs_drawdown,
)
from engine.ranking.stage import calculate_new_buy, calculate_stage
from engine.ranking.tactical import (
    calculate_health,
    calculate_penalty,
    calculate_regime_base_score,
    calculate_tactical_ranking,
    dma50_distance_score,
    dma50_slope_score,
    rank_tactical_scores,
    rs_drawdown_score,
)


def test_relative_20d_return_is_stock_return_minus_benchmark_return() -> None:
    dates = pd.date_range("2024-01-01", periods=21, freq="B")
    stock = pd.DataFrame({"date": dates, "Adj Close": np.linspace(100.0, 120.0, 21)})
    benchmark = pd.DataFrame({"date": dates, "Adj Close": np.linspace(100.0, 110.0, 21)})

    assert calculate_relative_20d_return(stock, benchmark) == pytest.approx(0.10)


def test_rs_drawdown_uses_maximum_from_previous_63_days_only() -> None:
    dates = pd.date_range("2024-01-01", periods=64, freq="B")
    stock_prices = np.full(64, 90.0)
    stock_prices[-2] = 100.0
    stock_prices[-1] = 80.0
    stock = pd.DataFrame({"date": dates, "Adj Close": stock_prices})
    benchmark = pd.DataFrame({"date": dates, "Adj Close": np.ones(64)})

    assert calculate_rs_drawdown(stock, benchmark, lookback=63) == pytest.approx(-0.20)


def test_tactical_score_mappings_cover_all_boundaries() -> None:
    assert rs_drawdown_score(0.0) == 100.0
    assert rs_drawdown_score(-0.05) == 80.0
    assert rs_drawdown_score(-0.10) == 60.0
    assert rs_drawdown_score(-0.15) == 40.0
    assert rs_drawdown_score(-0.20) == 20.0
    assert rs_drawdown_score(-0.25) == 0.0
    assert dma50_distance_score(0.10) == 100.0
    assert dma50_distance_score(0.05) == 80.0
    assert dma50_distance_score(0.0) == 60.0
    assert dma50_distance_score(-0.05) == 35.0
    assert dma50_distance_score(-0.10) == 10.0
    assert dma50_distance_score(-0.15) == 0.0
    assert dma50_slope_score(0.05) == 100.0
    assert dma50_slope_score(0.025) == 80.0
    assert dma50_slope_score(0.0) == 60.0
    assert dma50_slope_score(-0.025) == 30.0
    assert dma50_slope_score(-0.05) == 0.0


def test_health_and_penalty_follow_specified_weights_and_cap() -> None:
    assert calculate_health(80.0, 0.0, 0.0, 0.0) == pytest.approx(76.0)
    assert calculate_penalty(50.0) == 0.0
    assert calculate_penalty(49.0) == 1.0
    assert calculate_penalty(10.0) == 40.0
    assert calculate_new_buy(False, 35.0) is True
    assert calculate_new_buy(False, 34.99) is False
    assert calculate_new_buy(True, 100.0) is False


def test_regime_base_weights_change_by_regime() -> None:
    scores = (80.0, 60.0, 40.0)
    assert calculate_regime_base_score(*scores, "RISK_ON") == pytest.approx(64.0)
    assert calculate_regime_base_score(*scores, "WARNING") == pytest.approx(67.0)
    assert calculate_regime_base_score(*scores, "RISK_OFF") == pytest.approx(69.0)


def test_tactical_rank_uses_average_rank_for_ties() -> None:
    result = rank_tactical_scores(pd.Series([100.0, 100.0, 90.0], index=["A", "B", "C"]))

    pd.testing.assert_series_equal(
        result,
        pd.Series([1.5, 1.5, 3.0], index=["A", "B", "C"]),
    )


def test_stage4_requires_both_strict_conditions() -> None:
    dates = pd.date_range("2024-01-01", periods=220, freq="B")
    prices = pd.Series(np.linspace(200.0, 100.0, len(dates)), index=dates)

    metrics = calculate_stage(prices)

    assert metrics.stage == "Stage4"
    assert metrics.stage4 is True


def test_display_returns_include_ytd_mtd_and_weekly() -> None:
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2023-12-29"), *pd.bdate_range("2024-01-01", periods=19)]
    )
    prices = pd.DataFrame(
        {"date": dates, "Adj Close": np.arange(100.0, 120.0)}
    )

    returns = calculate_display_returns(prices)

    assert set(returns) == {"ytd", "mtd", "weekly"}
    assert returns["ytd"] == pytest.approx(119.0 / 100.0 - 1.0)
    assert returns["mtd"] == pytest.approx(119.0 / 100.0 - 1.0)
    assert returns["weekly"] == pytest.approx(119.0 / 114.0 - 1.0)


def test_display_returns_accept_timezone_aware_market_dates() -> None:
    dates = pd.date_range("2023-12-29", periods=21, freq="B", tz="America/New_York")
    prices = pd.DataFrame({"date": dates, "Adj Close": np.arange(100.0, 121.0)})

    returns = calculate_display_returns(prices)

    assert returns["ytd"] == pytest.approx(120.0 / 100.0 - 1.0)
    assert returns["mtd"] == pytest.approx(120.0 / 100.0 - 1.0)


def test_tactical_ranking_keeps_unranked_universe_rows() -> None:
    dates = pd.bdate_range("2024-01-01", periods=220)
    prices = pd.concat(
        [
            pd.DataFrame({"date": dates, "ticker": "AAA", "Adj Close": np.arange(100.0, 320.0)}),
            pd.DataFrame({"date": dates, "ticker": "BBB", "Adj Close": np.arange(100.0, 320.0)}),
            pd.DataFrame({"date": dates, "ticker": "SPY", "Adj Close": np.arange(100.0, 320.0)}),
        ],
        ignore_index=True,
    )
    universe = pd.DataFrame({"ticker": ["AAA", "BBB"]})
    base = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "base_rank": [1.0],
            "base_score": [80.0],
            "momentum_score": [80.0],
            "volume_score": [80.0],
            "beta_score": [80.0],
        }
    )

    result, exclusions = calculate_tactical_ranking(
        universe, base, prices, "SPY", "WARNING"
    )

    assert result["ticker"].tolist() == ["AAA", "BBB"]
    assert result.loc[result["ticker"] == "AAA", "tactical_rank"].notna().item()
    assert pd.isna(result.loc[result["ticker"] == "BBB", "tactical_rank"].item())
    assert "base_ranking_unavailable" in exclusions["BBB"]
