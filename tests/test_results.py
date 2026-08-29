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
