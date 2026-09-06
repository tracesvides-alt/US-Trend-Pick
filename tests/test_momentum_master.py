from __future__ import annotations

import json
import pickle
from pathlib import Path

import pandas as pd

from engine.integration.momentum_master import build_overview, write_overview


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "momentum_master"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "market_logic.py").write_text(
        "SECTOR_DEFINITIONS = {'Semiconductors': ['AAA', 'BBB']}\n"
        "THEMATIC_ETFS = {'Cloud': 'CLOU'}\n",
        encoding="utf-8",
    )
    (data / "last_updated.txt").write_text("2026-09-05 21:00:00", encoding="utf-8")
    (data / "momentum_cache.csv").write_text(
        "Ticker,Signal,Price,1d,5d,1mo,3mo,6mo,YTD,1y,RVOL,RSI\n"
        "AAA,Breakout,100,1,5,10,20,30,40,50,2,70\n"
        "BBB,,90,-1,2,8,18,28,38,48,1,55\n"
        "CCC,,80,0,1,3,6,12,20,30,0.8,45\n",
        encoding="utf-8",
    )
    (data / "metadata_cache.json").write_text(
        json.dumps(
            {
                "AAA": {"name": "Alpha"},
                "BBB": {"name": "Beta"},
                "CCC": {"name": "Gamma", "industry": "Healthcare"},
            }
        ),
        encoding="utf-8",
    )
    (data / "indices_cache.json").write_text(
        json.dumps({"^NDX": {"name": "ナス100", "returns": {"5d": 2.5}, "price": 100}}),
        encoding="utf-8",
    )
    return root


def test_builds_top_worst_indices_and_sector_heatmap(tmp_path: Path) -> None:
    document = build_overview(_source(tmp_path), as_of="2026-09-05")

    assert document.status == "AVAILABLE"
    assert document.rankings["1d"].top[0].ticker == "AAA"
    assert document.rankings["1d"].worst[0].ticker == "BBB"
    assert document.rankings["1d"].top[0].return_value == 1.0
    assert document.indices[0].ticker == "^NDX"
    sectors = {item.sector: item for item in document.sectors}
    assert sectors["Semiconductors"].count == 2
    assert sectors["Semiconductors"].returns["1d"] == 0.0
    assert [member.ticker for member in sectors["Semiconductors"].members] == ["AAA", "BBB"]
    assert sectors["Semiconductors"].members[0].returns["5d"] == 5.0
    assert sectors["Healthcare"].count == 1


def test_writes_aliases_and_missing_optional_source_as_unavailable(tmp_path: Path) -> None:
    output = tmp_path / "momentum-overview.json"
    document = build_overview(tmp_path / "missing", as_of="2026-09-05")
    write_overview(document, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["asOf"] == "2026-09-05"
    assert payload["status"] == "UNAVAILABLE"
    assert payload["rankings"]["1d"] == {"top": [], "worst": []}


def test_uses_price_as_of_and_exact_trading_day_windows(tmp_path: Path) -> None:
    root = _source(tmp_path)
    history = {
        "AAA": pd.DataFrame(
            {"Close": [100, 101, 102, 103, 104, 110]},
            index=pd.date_range("2026-09-01", periods=6, freq="D"),
        )
    }
    with (root / "data" / "history_cache.pkl").open("wb") as handle:
        pickle.dump(history, handle)

    document = build_overview(root)
    aaa = document.rankings["5d"].top[0]

    assert document.as_of == "2026-09-06"
    assert document.price_as_of == "2026-09-06"
    assert document.cache_updated_at == "2026-09-05 21:00:00"
    assert aaa.return_value == 10.0
