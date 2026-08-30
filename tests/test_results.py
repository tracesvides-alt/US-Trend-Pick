from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from engine.results.builder import build_result_document, write_result_outputs
from engine.results.models import ResultDocument


def _inputs() -> dict:
    return {
        "base_ranking": [
            {"ticker": "AAA", "base_rank": 1.0},
            {"ticker": "BBB", "base_rank": 2.0},
            {"ticker": "CCC", "base_rank": 3.0},
        ],
        "tactical_ranking": [
            {"ticker": "AAA", "tactical_rank": 2.0},
            {"ticker": "BBB", "tactical_rank": 1.0},
            {"ticker": "CCC", "tactical_rank": 3.0},
        ],
        "market_regime": {
            "regime": "WARNING",
            "market_regime_score": 55.0,
            "data_status": "COMPLETE",
        },
        "portfolio_payload": {
            "portfolio_status": "CONFIRMED",
            "holdings": [
                {"ticker": "BBB", "weight": 0.1, "status": "Keep"},
                {"ticker": "CCC", "weight": 0.1, "status": "Entry"},
            ],
            "theme_review": [],
        },
        "metadata": {
            "data_status": "COMPLETE",
            "benchmark_sources": {"sp500": "SPY", "nasdaq100": "QQQ"},
        },
        "universe_count": 3,
    }


def test_result_document_uses_frontend_top_level_schema() -> None:
    values = _inputs()
    previous = build_result_document(
        date(2026, 8, 22),
        [
            {"ticker": "AAA", "base_rank": 1.0},
            {"ticker": "BBB", "base_rank": 2.0},
        ],
        [
            {"ticker": "AAA", "tactical_rank": 1.0},
            {"ticker": "BBB", "tactical_rank": 2.0},
        ],
        values["market_regime"],
        {
            "portfolio_status": "CONFIRMED",
            "holdings": [{"ticker": "AAA", "weight": 0.1, "status": "Keep"}],
        },
        values["metadata"],
        2,
    )
    document = build_result_document(date(2026, 8, 29), previous_result=previous.model_dump(mode="json", by_alias=True), **values)

    payload = document.model_dump(mode="json", by_alias=True)
    assert set(payload) >= {
        "asOf",
        "status",
        "marketRegime",
        "dataHealth",
        "portfolio",
        "baseRanking",
        "tacticalRanking",
        "rotation",
    }
    assert document.status == "OFFICIAL"
    assert document.data_health.ranking_status == "OFFICIAL"


def test_previous_rank_and_portfolio_transitions_are_calculated() -> None:
    values = _inputs()
    previous = build_result_document(
        date(2026, 8, 22),
        values["base_ranking"],
        [
            {"ticker": "AAA", "tactical_rank": 1.0},
            {"ticker": "BBB", "tactical_rank": 2.0},
            {"ticker": "CCC", "tactical_rank": 3.0},
        ],
        values["market_regime"],
        {
            "portfolio_status": "CONFIRMED",
            "holdings": [{"ticker": "AAA", "weight": 0.1, "status": "Keep"},
                         {"ticker": "BBB", "weight": 0.1, "status": "Keep"}],
        },
        values["metadata"],
        3,
    )
    document = build_result_document(
        date(2026, 8, 29),
        previous_result=previous.model_dump(mode="json", by_alias=True),
        **values,
    )

    changes = {row.ticker: row for row in document.rotation.rank_change}
    assert changes["AAA"].rank_change == pytest.approx(-1.0)
    assert changes["BBB"].rank_change == pytest.approx(1.0)
    assert [row.ticker for row in document.rotation.portfolio_in] == ["CCC"]
    assert [row.ticker for row in document.rotation.portfolio_out] == ["AAA"]
    assert [row.ticker for row in document.rotation.hold] == ["BBB"]


def test_automatic_theme_snapshot_is_embedded_without_changing_rankings() -> None:
    values = _inputs()
    document = build_result_document(
        date(2026, 8, 29),
        theme_snapshot=[
            {
                "ticker": "BBB",
                "primary_theme": "AI Networking",
                "theme_score": 87.0,
                "second_theme": "ASIC / Custom Silicon",
                "second_theme_score": 42.0,
                "confidence": "HIGH",
                "as_of": "2026-08-29",
            }
        ],
        theme_changes=[
            {
                "ticker": "BBB",
                "previous_theme": "Cloud / AI Infrastructure",
                "new_theme": "AI Networking",
                "as_of": "2026-08-29",
                "reason": "TWO_CONSECUTIVE_WEEKLY_WINS",
            }
        ],
        **values,
    )

    tactical = next(row for row in document.tactical_ranking if row.ticker == "BBB")
    assert tactical.primary_theme == "AI Networking"
    assert tactical.theme_score == 87.0
    assert document.theme_snapshot[0].confidence == "HIGH"
    assert document.theme_changes[0].new_theme == "AI Networking"


def test_result_contains_nested_component_explanations_and_rank_history() -> None:
    values = _inputs()
    values["base_ranking"] = [
        {
            "ticker": "AAA",
            "momentum_raw": 1.8,
            "momentum_score": 100.0,
            "momentum_rank": 1.0,
            "volume_expansion_raw": 2.1,
            "volume_score": 80.0,
            "volume_expansion_rank": 2.0,
            "beta_raw": 1.6,
            "beta_score": 60.0,
            "beta_rank": 3.0,
            "base_score": 84.0,
            "base_rank": 1.0,
        },
        {
            "ticker": "BBB",
            "momentum_raw": 1.1,
            "momentum_score": 80.0,
            "momentum_rank": 2.0,
            "volume_expansion_raw": 1.5,
            "volume_score": 100.0,
            "volume_expansion_rank": 1.0,
            "beta_raw": 1.2,
            "beta_score": 80.0,
            "beta_rank": 2.0,
            "base_score": 86.0,
            "base_rank": 2.0,
        },
        {"ticker": "CCC", "base_rank": 3.0, "base_score": 40.0},
    ]
    values["tactical_ranking"] = [
        {
            "ticker": "AAA",
            "base_rank": 1.0,
            "base_score": 84.0,
            "tactical_rank": 2.0,
            "tactical_score": 82.0,
            "tactical_previous_rank": 4.0,
            "health": 76.0,
            "penalty": 0.0,
            "relative_20d_raw": 0.08,
            "relative_20d_score": 90.0,
            "relative_20d_rank": 2.0,
            "rs_drawdown_raw": -0.04,
            "rs_drawdown_score": 84.0,
            "dma50_distance_raw": 0.07,
            "dma50_distance_score": 88.0,
            "dma50_slope_raw": 0.03,
            "dma50_slope_score": 82.0,
        },
        {"ticker": "BBB", "tactical_rank": 1.0, "tactical_score": 90.0},
        {"ticker": "CCC", "tactical_rank": 3.0, "tactical_score": 40.0},
    ]

    document = build_result_document(date(2026, 8, 29), **values)
    row = next(item for item in document.tactical_ranking if item.ticker == "AAA")

    assert row.base is not None
    assert row.base.rank == 1.0
    assert row.base.score == 84.0
    assert row.base_components is not None
    assert row.base_components.momentum.rank == 1.0
    assert row.base_components.volume_expansion.score == 80.0
    assert row.tactical is not None
    assert row.tactical.previous_rank == 4.0
    assert row.tactical.rank_change == 2.0
    assert row.tactical_components is not None
    assert row.tactical_components.relative_20d.rank == 2.0
    assert row.tactical_components.dma50_slope.raw == 0.03


def test_nested_explanation_schema_rejects_invalid_component_score() -> None:
    values = _inputs()
    document = build_result_document(date(2026, 8, 29), **values)
    payload = document.model_dump(mode="json", by_alias=True)
    payload["tacticalRanking"][0]["base_components"]["momentum"]["score"] = 101.0

    with pytest.raises(ValidationError):
        ResultDocument.model_validate(payload)


def test_theme_pending_status_is_separate_from_ranking_status() -> None:
    values = _inputs()
    values["portfolio_payload"] = {
        "portfolio_status": "THEME_REVIEW_REQUIRED",
        "holdings": [],
        "theme_review": [
            {
                "ticker": "AAA",
                "tactical_rank": 1.0,
                "theme": None,
                "reason": "THEME_REVIEW_REQUIRED",
            }
        ],
    }

    document = build_result_document(date(2026, 8, 29), **values)

    assert document.status == "RANKING_OFFICIAL_PORTFOLIO_PENDING"
    assert document.data_health.ranking_status == "OFFICIAL"
    assert document.portfolio_status == "THEME_REVIEW_REQUIRED"
    assert document.theme_review[0].ticker == "AAA"


def test_incomplete_data_takes_precedence_over_theme_pending() -> None:
    values = _inputs()
    values["metadata"] = {
        "data_status": "INCOMPLETE",
        "failure_tickers": ["CCC"],
        "benchmark_sources": {},
    }
    values["portfolio_payload"] = {
        "portfolio_status": "THEME_REVIEW_REQUIRED",
        "holdings": [],
    }

    document = build_result_document(date(2026, 8, 29), **values)

    assert document.status == "INCOMPLETE"
    assert document.data_health.missing_tickers == ["CCC"]


def test_outputs_are_validated_before_any_file_is_saved(tmp_path) -> None:
    values = _inputs()
    document = build_result_document(date(2026, 8, 29), **values)
    payload = document.model_dump(mode="json", by_alias=True)
    payload.pop("tacticalRanking")

    with pytest.raises(ValidationError):
        write_result_outputs(payload, tmp_path)

    assert not (tmp_path / "2026-08-29.json").exists()
    assert not (tmp_path / "latest.json").exists()


def test_written_history_and_latest_are_schema_valid(tmp_path) -> None:
    values = _inputs()
    document = build_result_document(date(2026, 8, 29), **values)
    history_path, latest_path = write_result_outputs(document, tmp_path)

    assert history_path.name == "2026-08-29.json"
    assert latest_path.name == "latest.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    theme_review = json.loads((tmp_path / "theme-review.json").read_text(encoding="utf-8"))
    ResultDocument.model_validate(history)
    assert latest == history
    assert theme_review == []
