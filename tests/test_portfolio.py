from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from engine.portfolio.builder import build_portfolio, theme_constraint_ok
from engine.portfolio.theme import active_theme_map, load_theme_history


def _tactical_rows(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "base_rank": 1.0,
        "base_score": 80.0,
        "regime_base_score": 80.0,
        "tactical_score": 80.0,
        "health": 80.0,
        "penalty": 0.0,
        "stage": "Normal",
        "new_buy": True,
        "ytd": 0.1,
        "mtd": 0.05,
        "weekly": 0.02,
    }
    prepared = []
    for row in rows:
        prepared.append({**defaults, **row})
    return pd.DataFrame(prepared)


def test_theme_history_applies_only_records_active_on_measurement_date(tmp_path) -> None:
    path = tmp_path / "theme_history.yaml"
    path.write_text(
        """themes:
  - ticker: AAA
    theme: Legacy
    effective_from: 2024-01-01
    effective_to: 2024-12-31
  - ticker: AAA
    theme: Current
    effective_from: 2025-01-01
    effective_to: null
  - ticker: BBB
    theme: Future
    effective_from: 2027-01-01
    effective_to: null
""",
        encoding="utf-8",
    )

    records = load_theme_history(path)

    assert active_theme_map(records, date(2024, 6, 1)) == {"AAA": "Legacy"}
    assert active_theme_map(records, date(2026, 1, 1)) == {"AAA": "Current"}


def test_theme_history_rejects_overlapping_active_records(tmp_path) -> None:
    path = tmp_path / "theme_history.yaml"
    path.write_text(
        """themes:
  - ticker: AAA
    theme: One
    effective_from: 2024-01-01
    effective_to: null
  - ticker: AAA
    theme: Two
    effective_from: 2025-01-01
    effective_to: null
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="overlapping"):
        active_theme_map(load_theme_history(path), date(2026, 1, 1))


def test_second_same_theme_requires_top10_and_next_alternative_rank16_or_lower() -> None:
    first = {"ticker": "AAA", "theme": "Alpha", "tactical_rank": 1}
    second = {"ticker": "BBB", "theme": "Alpha", "tactical_rank": 2}
    alternative = {"ticker": "CCC", "theme": "Beta", "tactical_rank": 16}

    assert theme_constraint_ok(second, [first], [first, second, alternative]) is True
    assert theme_constraint_ok(second, [first], [first, second, {**alternative, "tactical_rank": 15}]) is False


def test_third_same_theme_is_allowed_only_when_all_three_are_top5() -> None:
    selected = [
        {"ticker": "AAA", "theme": "Alpha", "tactical_rank": 1},
        {"ticker": "BBB", "theme": "Alpha", "tactical_rank": 2},
    ]
    third = {"ticker": "CCC", "theme": "Alpha", "tactical_rank": 5}
    fourth = {"ticker": "DDD", "theme": "Alpha", "tactical_rank": 6}

    assert theme_constraint_ok(third, selected, selected + [third]) is True
    assert theme_constraint_ok(fourth, selected, selected + [fourth]) is False


def test_previous_portfolio_statuses_keep_hold_and_rotation() -> None:
    tactical = _tactical_rows(
        [
            {"ticker": "AAA", "tactical_rank": 1},
            {"ticker": "DDD", "tactical_rank": 2},
            {"ticker": "BBB", "tactical_rank": 12},
            {"ticker": "CCC", "tactical_rank": 20},
        ]
    )
    themes = {"AAA": "Alpha", "BBB": "Beta", "CCC": "Gamma", "DDD": "Delta"}
    previous = [
        {"ticker": "AAA", "weight": 0.1},
        {"ticker": "BBB", "weight": 0.1},
        {"ticker": "CCC", "weight": 0.1},
    ]

    result = build_portfolio(tactical, themes, previous, target_holdings=2)
    statuses = {row["ticker"]: row["status"] for row in result.holdings}

    assert result.selected_count == 2
    assert statuses["AAA"] == "Keep"
    assert statuses["BBB"] == "Hold"
    assert statuses["CCC"] == "Rotation"
    assert result.portfolio_status == "CONFIRMED"
    assert {
        "ticker",
        "weight",
        "theme",
        "base_rank",
        "tactical_rank",
        "status",
        "ytd",
        "mtd",
        "weekly",
    } <= set(result.holdings[0])


def test_unclassified_top20_requires_review_but_does_not_change_ranking() -> None:
    tactical = _tactical_rows(
        [
            {"ticker": "AAA", "tactical_rank": 1},
            {"ticker": "BBB", "tactical_rank": 2},
        ]
    )

    result = build_portfolio(tactical, {"BBB": "Beta"}, target_holdings=1)

    assert result.portfolio_status == "THEME_REVIEW_REQUIRED"
    assert result.selected_count == 1
    assert result.theme_review == [
        {"ticker": "AAA", "tactical_rank": 1.0, "theme": None, "reason": "THEME_REVIEW_REQUIRED"}
    ]
    assert result.holdings[0]["ticker"] == "BBB"


def test_three_top5_same_theme_can_fill_three_positions() -> None:
    tactical = _tactical_rows(
        [
            {"ticker": "AAA", "tactical_rank": 1},
            {"ticker": "BBB", "tactical_rank": 2},
            {"ticker": "CCC", "tactical_rank": 3},
            {"ticker": "DDD", "tactical_rank": 16},
        ]
    )
    themes = {"AAA": "Alpha", "BBB": "Alpha", "CCC": "Alpha", "DDD": "Beta"}

    result = build_portfolio(tactical, themes, target_holdings=3)

    assert result.selected_count == 3
    assert [row["ticker"] for row in result.holdings] == ["AAA", "BBB", "CCC"]
    assert all(row["weight"] == 0.1 for row in result.holdings)


def test_confirmed_portfolio_has_ten_equal_weight_holdings() -> None:
    tickers = [f"TICKER{index}" for index in range(10)]
    tactical = _tactical_rows(
        [{"ticker": ticker, "tactical_rank": index + 1} for index, ticker in enumerate(tickers)]
    )
    themes = {ticker: f"Theme{index}" for index, ticker in enumerate(tickers)}

    result = build_portfolio(tactical, themes)

    selected = [row for row in result.holdings if row["weight"] > 0]
    assert result.portfolio_status == "CONFIRMED"
    assert result.selected_count == 10
    assert len(selected) == 10
    assert sum(row["weight"] for row in selected) == pytest.approx(1.0)
