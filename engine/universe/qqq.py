"""QQQ holdings acquisition and parsing."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import requests
from bs4 import BeautifulSoup

from engine.dates import measurement_date
from engine.universe.models import Holding, SourceResult

INVESCO_HOLDINGS_URL = (
    "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
    "?ticker=QQQ&action=download"
)
NASDAQ_100_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
COMPANIESMARKETCAP_URL = "https://companiesmarketcap.com/invesco-nasdaq-100-etf/holdings/"
MIN_EXPECTED_HOLDINGS = 80
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (US-Trend-Pick/0.1)",
    "Accept": "application/json,text/csv,text/html,*/*",
}


def _deduplicate(holdings: list[Holding]) -> list[Holding]:
    unique: dict[str, Holding] = {}
    for holding in holdings:
        key = holding.ticker.strip().upper()
        if key and key not in unique:
            unique[key] = holding.model_copy(update={"ticker": key})
    return list(unique.values())


def _holding_from_mapping(row: dict[str, Any]) -> Holding | None:
    ticker = next(
        (
            row.get(key)
            for key in (
                "symbol",
                "ticker",
                "Ticker",
                "Symbol",
                "HoldingsTicker",
                "Holding Ticker",
                "Ticker Symbol",
            )
            if row.get(key)
        ),
        None,
    )
    name = next(
        (
            row.get(key)
            for key in (
                "companyName",
                "issuerName",
                "name",
                "Name",
                "Security",
                "Description",
                "Holding Name",
            )
            if row.get(key)
        ),
        None,
    )
    if not ticker or not name:
        return None
    return Holding(ticker=str(ticker).strip(), company_name=str(name).strip())


def _parse_json(payload: str) -> list[Holding]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return []
    rows: Any = []
    if isinstance(document, dict):
        data = document.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            rows = data["data"].get("rows", [])
        elif isinstance(data, dict):
            rows = data.get("rows", data.get("holdings", []))
        elif isinstance(document.get("response"), dict):
            rows = document["response"].get("docs", [])
        else:
            rows = document.get("holdings", [])
    if not isinstance(rows, list):
        return []
    return _deduplicate(
        [holding for row in rows if isinstance(row, dict) for holding in [_holding_from_mapping(row)] if holding]
    )


def _parse_csv(payload: str) -> list[Holding]:
    lines = payload.splitlines()
    header_position: int | None = None
    for position, line in enumerate(lines):
        fields = [field.strip().lower() for field in next(csv.reader([line]))]
        if {
            "ticker",
            "symbol",
            "holdings ticker",
            "holding ticker",
            "ticker symbol",
        }.intersection(fields) and {
            "name",
            "company name",
            "description",
            "security",
            "holding name",
        }.intersection(fields):
            header_position = position
            break
    if header_position is None:
        return []
    rows = csv.DictReader(io.StringIO("\n".join(lines[header_position:])))
    holdings = []
    for row in rows:
        holding = _holding_from_mapping(dict(row))
        if holding:
            holdings.append(holding)
    return _deduplicate(holdings)


def _parse_html(payload: str) -> list[Holding]:
    soup = BeautifulSoup(payload, "html.parser")
    holdings: list[Holding] = []
    for table in soup.find_all("table"):
        headers = [cell.get_text(" ", strip=True).lower() for cell in table.find_all("th")]
        if not headers:
            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if len(cells) >= 4 and cells[0].endswith("%"):
                    holdings.append(Holding(ticker=cells[2], company_name=cells[1]))
            continue
        if not {"symbol", "ticker"}.intersection(headers):
            continue
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) < 3:
                continue
            ticker_position = headers.index("symbol") if "symbol" in headers else headers.index("ticker")
            name_position = headers.index("name") if "name" in headers else headers.index("description")
            if ticker_position < len(cells) and name_position < len(cells):
                holdings.append(
                    Holding(ticker=cells[ticker_position], company_name=cells[name_position])
                )
    return _deduplicate(holdings)


def parse_qqq_holdings(payload: bytes | str) -> list[Holding]:
    """Parse Invesco CSV, Nasdaq JSON, or a tabular HTML fixture."""
    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) else payload
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json(text)
    csv_holdings = _parse_csv(text)
    return csv_holdings or _parse_html(text)


def _request(session: requests.Session, url: str, timeout: int) -> requests.Response:
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def _is_complete(holdings: list[Holding]) -> bool:
    return len(holdings) >= MIN_EXPECTED_HOLDINGS


def fetch_qqq_holdings(
    session: requests.Session | None = None,
    timeout: int = 30,
) -> SourceResult:
    """Fetch complete QQQ holdings, recording failed sources for diagnostics."""
    client = session or requests.Session()
    errors: list[str] = []
    for url in (INVESCO_HOLDINGS_URL, NASDAQ_100_URL, COMPANIESMARKETCAP_URL):
        try:
            response = _request(client, url, timeout)
            holdings = parse_qqq_holdings(response.content)
            if _is_complete(holdings):
                return SourceResult(
                    name="QQQ",
                    holdings=holdings,
                    selected_source=url,
                    as_of=measurement_date(),
                    errors=errors,
                )
            errors.append(f"{url}: incomplete response ({len(holdings)} holdings)")
        except (requests.RequestException, UnicodeError) as exc:
            errors.append(f"{url}: {exc}")
    return SourceResult(name="QQQ", errors=errors)
