from __future__ import annotations

import numpy as np
import pandas as pd

from tests.fixtures.golden_ranking import build_golden_inputs
from engine.ranking.base import calculate_base_score
from engine.ranking.base import calculate_base_ranking
from engine.ranking.beta import calculate_beta, shrink_beta
from engine.ranking.momentum import calculate_momentum
from engine.ranking.percentile import percentile_score
from engine.ranking.volume import calculate_dollar_volume_expansion


def test_percentile_uses_average_rank_for_ties() -> None:
    scores = percentile_score(pd.Series([10.0, 10.0, 5.0], index=["A", "B", "C"]))

    pd.testing.assert_series_equal(
        scores,
        pd.Series([75.0, 75.0, 0.0], index=["A", "B", "C"]),
    )


def test_momentum_excludes_the_latest_21_observations() -> None:
    values = np.full(260, 100.0)
    values[238] = 150.0  # latest index - 22: last included observation
    values[7] = 100.0  # latest index - 253: 252 observations back
    values[239:] = 10_000.0  # must not influence 12-1M momentum
    prices = pd.Series(values, index=pd.date_range("2024-01-01", periods=260, freq="B"))

    assert calculate_momentum(prices) == 0.5


def test_dollar_volume_uses_recent_63_and_prior_189_style_windows() -> None:
    frame = pd.DataFrame(
        {
            "Close": [1.0] * 5,
            "Volume": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )

    # Recent mean = (40 + 50) / 2 = 45; prior mean = 20; 45 / 20 = 2.25.
    assert calculate_dollar_volume_expansion(frame, recent_days=2, prior_days=3) == 2.25


def test_dollar_volume_rejects_invalid_raw_price_or_volume_rows() -> None:
    frame = pd.DataFrame(
        {
            "Close": [100.0, 0.0, 100.0, 100.0],
            "Volume": [10.0, 10.0, -1.0, 10.0],
        }
    )

    assert np.isnan(calculate_dollar_volume_expansion(frame, recent_days=2, prior_days=2))


def test_beta_shrink_matches_the_specified_formula() -> None:
    assert shrink_beta(2.0, 60) == 2.0
    assert shrink_beta(2.0, 15) == 1.5


def test_beta_is_neutral_for_12_to_23_month_histories() -> None:
    dates = pd.bdate_range("2024-01-01", periods=400)
    benchmark = pd.DataFrame(
        {"date": dates, "Adj Close": 100.0 * (1.001 ** np.arange(len(dates)))}
    )
    asset = pd.DataFrame(
        {"date": dates, "Adj Close": 50.0 * (1.002 ** np.arange(len(dates)))}
    )

    metrics = calculate_beta(asset, benchmark)

    assert 12 <= metrics.months < 24
    assert metrics.status == "NEUTRAL_12_23M"
    assert metrics.beta_score == 50.0


def test_base_score_weights_are_45_30_25() -> None:
    assert calculate_base_score(80.0, 60.0, 40.0) == 64.0


def test_base_ranking_golden_fixture_matches_expected_order_and_scores() -> None:
    tickers, prices, benchmark = build_golden_inputs()

    result, excluded = calculate_base_ranking(tickers, prices, benchmark, "SPY")

    expected = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "momentum_raw": 0.9352226720647774,
                "momentum_score": 100.0,
                "volume_expansion_raw": 1.5378228659654025,
                "volume_score": 100.0,
                "beta_raw": 10.041762917147144,
                "beta_score": 50.0,
                "base_score": 87.5,
                "base_rank": 1.0,
            },
            {
                "ticker": "BBB",
                "momentum_raw": 0.22063037249283668,
                "momentum_score": 50.0,
                "volume_expansion_raw": 1.0124235850916978,
                "volume_score": 50.0,
                "beta_raw": 1.7060696856969124,
                "beta_score": 50.0,
                "base_score": 50.0,
                "base_rank": 2.0,
            },
            {
                "ticker": "CCC",
                "momentum_raw": -0.1589814177563662,
                "momentum_score": 0.0,
                "volume_expansion_raw": 0.8188709443197765,
                "volume_score": 0.0,
                "beta_raw": 0.5492832100896348,
                "beta_score": 50.0,
                "base_score": 12.5,
                "base_rank": 3.0,
            },
        ]
    )

    assert excluded == {}
    pd.testing.assert_frame_equal(
        result,
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
