"""QQQJ holdings acquisition and parsing."""

from __future__ import annotations

import requests

from engine.dates import measurement_date
from engine.universe.models import Holding, SourceResult
from engine.universe.qqq import parse_qqq_holdings

INVESCO_HOLDINGS_URL = (
    "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
    "?ticker=QQQJ&action=download"
)
NASDAQ_NEXTGEN_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaqnextgen100"
COMPANIESMARKETCAP_URL = (
    "https://companiesmarketcap.com/invesco-nasdaq-next-gen-100-etf/holdings/"
)
MIN_EXPECTED_HOLDINGS = 80
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (US-Trend-Pick/0.1)",
    "Accept": "application/json,text/csv,text/html,*/*",
}


def parse_qqqj_holdings(payload: bytes | str) -> list[Holding]:
    """Parse Invesco CSV, Nasdaq JSON, or the full fallback holdings HTML table."""
    return parse_qqq_holdings(payload)


def _request(session: requests.Session, url: str, timeout: int) -> requests.Response:
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_qqqj_holdings(
    session: requests.Session | None = None,
    timeout: int = 30,
) -> SourceResult:
    """Fetch complete QQQJ holdings, recording failed sources for diagnostics."""
    client = session or requests.Session()
    errors: list[str] = []
    for url in (INVESCO_HOLDINGS_URL, NASDAQ_NEXTGEN_URL, COMPANIESMARKETCAP_URL):
        try:
            response = _request(client, url, timeout)
            holdings = parse_qqqj_holdings(response.content)
            if len(holdings) >= MIN_EXPECTED_HOLDINGS:
                return SourceResult(
                    name="QQQJ",
                    holdings=holdings,
                    selected_source=url,
                    as_of=measurement_date(),
                    errors=errors,
                )
            errors.append(f"{url}: incomplete response ({len(holdings)} holdings)")
        except (requests.RequestException, UnicodeError) as exc:
            errors.append(f"{url}: {exc}")
    return SourceResult(name="QQQJ", errors=errors)
