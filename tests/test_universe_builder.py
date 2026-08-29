"""Offline tests for ticker normalization and universe merging."""

from datetime import date

from engine.universe.builder import (
    load_ticker_aliases,
    merge_universes,
    normalize_ticker,
    write_snapshot,
)
from engine.universe.models import Holding, SourceResult


def test_normalize_ticker_applies_vendor_alias() -> None:
    assert normalize_ticker("brk.b", {"BRK.B": "BRK-B"}) == "BRK-B"
    assert normalize_ticker("NYSE: AAPL") == "AAPL"


def test_load_ticker_aliases_from_repository_config() -> None:
    aliases = load_ticker_aliases()

    assert aliases["BRK.B"] == "BRK-B"
    assert aliases["BF.B"] == "BF-B"


def test_merge_universes_deduplicates_and_tracks_sources(tmp_path) -> None:
    as_of = date(2026, 8, 29)
    spy = SourceResult(
        name="SPY",
        selected_source="fixture-spy",
        holdings=[
            Holding(ticker="BRK.B", company_name="Berkshire Hathaway Inc."),
            Holding(ticker="CASH", company_name="Cash"),
        ],
    )
    qqq = SourceResult(
        name="QQQ",
        selected_source="fixture-qqq",
        holdings=[
            Holding(ticker="BRK-B", company_name="Berkshire Hathaway Inc."),
            Holding(ticker="MSFT", company_name="Microsoft Corporation"),
        ],
    )
    qqqj = SourceResult(
        name="QQQJ",
        selected_source="fixture-qqqj",
        holdings=[Holding(ticker="MSFT", company_name="Microsoft Corporation")],
    )

    members, duplicate_removed = merge_universes(
        spy,
        qqq,
        qqqj,
        as_of=as_of,
        aliases={"BRK.B": "BRK-B"},
    )
    output_path = write_snapshot(members, tmp_path, as_of=as_of)

    assert [member.ticker for member in members] == ["BRK-B", "MSFT"]
    assert duplicate_removed == 2
    assert members[0].source_spy is True
    assert members[0].source_qqq is True
    assert members[1].source_qqqj is True
    assert output_path.read_text(encoding="utf-8").splitlines()[0] == (
        "ticker,company_name,source_spy,source_qqq,source_qqqj,as_of"
    )
