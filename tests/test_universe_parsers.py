"""Fixture-only tests for universe response parsers."""

from pathlib import Path

from engine.universe.qqq import parse_qqq_holdings
from engine.universe.qqqj import parse_qqqj_holdings
from engine.universe.spy import parse_spy_holdings

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_spy_csv_fixture() -> None:
    holdings = parse_spy_holdings((FIXTURES / "spy_holdings.csv").read_bytes())

    assert [(item.ticker, item.company_name) for item in holdings] == [
        ("AAPL", "Apple Inc."),
        ("BRK.B", "Berkshire Hathaway Inc. Class B"),
        ("CASH", "Cash"),
    ]


def test_parse_qqq_nasdaq_json_fixture() -> None:
    payload = (FIXTURES / "qqq_holdings.json").read_text(encoding="utf-8")

    holdings = parse_qqq_holdings(payload)

    assert [item.ticker for item in holdings] == ["AAPL", "MSFT"]


def test_parse_qqqj_html_fixture() -> None:
    payload = (FIXTURES / "qqqj_holdings.html").read_text(encoding="utf-8")

    holdings = parse_qqqj_holdings(payload)

    assert [(item.ticker, item.company_name) for item in holdings] == [
        ("EXHL", "Example Health, Inc."),
        ("EXSW", "Example Software, Inc."),
    ]
