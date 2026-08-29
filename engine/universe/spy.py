"""SPY holdings acquisition and parsing."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from engine.dates import measurement_date
from engine.universe.models import Holding, SourceResult

SSGA_HOLDINGS_URLS = (
    "https://www.ssga.com/us/en/individual/etfs/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
    "https://www.ssga.com/us/en/institutional/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
)
SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
MIN_EXPECTED_HOLDINGS = 400
DEFAULT_HEADERS = {"User-Agent": "US-Trend-Pick/0.1"}
_XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _cell_column(reference: str) -> str:
    """Return the alphabetic column portion of an XLSX cell reference."""
    match = re.match(r"([A-Z]+)", reference.upper())
    return match.group(1) if match else ""


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Read shared strings from an XLSX archive."""
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(item.itertext()) for item in root.findall("main:si", _XLSX_NS)]


def _xlsx_cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    value = cell.findtext("main:v", default="", namespaces=_XLSX_NS)
    if cell.attrib.get("t") == "s" and value:
        try:
            return shared[int(value)].strip()
        except (IndexError, ValueError):
            return ""
    if cell.attrib.get("t") == "inlineStr":
        return "".join(cell.itertext()).strip()
    return value.strip()


def _parse_spy_xlsx(payload: bytes) -> list[Holding]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        shared = _shared_strings(archive)
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows = root.findall(".//main:sheetData/main:row", _XLSX_NS)
    header_index: dict[str, str] | None = None
    holdings: list[Holding] = []
    for row in rows:
        cells = {
            _cell_column(cell.attrib.get("r", "")): _xlsx_cell_value(cell, shared)
            for cell in row.findall("main:c", _XLSX_NS)
        }
        if not header_index and {value.lower() for value in cells.values()} >= {
            "name",
            "ticker",
        }:
            header_index = {value.lower(): column for column, value in cells.items()}
            continue
        if not header_index:
            continue
        ticker = cells.get(header_index.get("ticker", ""), "").strip()
        name = cells.get(header_index.get("name", ""), "").strip()
        if ticker and name:
            holdings.append(Holding(ticker=ticker, company_name=name))
    return _deduplicate(holdings)


def _parse_tabular_text(payload: str) -> list[Holding]:
    """Parse a CSV payload after locating its Name/Ticker header row."""
    lines = payload.splitlines()
    header_position: int | None = None
    for position, line in enumerate(lines):
        fields = [field.strip().lower() for field in next(csv.reader([line]))]
        if "name" in fields and "ticker" in fields:
            header_position = position
            break
    if header_position is None:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_position:])))
    holdings = []
    for row in reader:
        ticker = (row.get("Ticker") or row.get("Symbol") or "").strip()
        name = (row.get("Name") or row.get("Security") or "").strip()
        if ticker and name:
            holdings.append(Holding(ticker=ticker, company_name=name))
    return _deduplicate(holdings)


def parse_spy_holdings(payload: bytes | str) -> list[Holding]:
    """Parse State Street XLSX or a CSV fixture with Name/Ticker columns."""
    if isinstance(payload, bytes) and payload[:2] == b"PK":
        return _parse_spy_xlsx(payload)
    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) else payload
    return _parse_tabular_text(text)


def parse_sp500_wikipedia_html(payload: str) -> list[Holding]:
    """Parse the public S&P 500 constituents table used as a fallback."""
    soup = BeautifulSoup(payload, "html.parser")
    table = soup.find("table", id="constituents")
    if table is None:
        return []
    holdings = []
    for row in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if len(cells) >= 2 and cells[0].lower() != "symbol":
            holdings.append(Holding(ticker=cells[0], company_name=cells[1]))
    return _deduplicate(holdings)


def _deduplicate(holdings: list[Holding]) -> list[Holding]:
    unique: dict[str, Holding] = {}
    for holding in holdings:
        key = holding.ticker.strip().upper()
        if key and key not in unique:
            unique[key] = holding.model_copy(update={"ticker": key})
    return list(unique.values())


def _is_complete(holdings: list[Holding]) -> bool:
    return len(holdings) >= MIN_EXPECTED_HOLDINGS


def _request(session: requests.Session, url: str, timeout: int) -> requests.Response:
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_spy_holdings(
    session: requests.Session | None = None,
    timeout: int = 30,
) -> SourceResult:
    """Fetch complete SPY holdings, recording failed sources for diagnostics."""
    client = session or requests.Session()
    errors: list[str] = []
    for url in SSGA_HOLDINGS_URLS:
        try:
            response = _request(client, url, timeout)
            holdings = parse_spy_holdings(response.content)
            if _is_complete(holdings):
                return SourceResult(
                    name="SPY",
                    holdings=holdings,
                    selected_source=url,
                    as_of=measurement_date(),
                    errors=errors,
                )
            errors.append(f"{url}: incomplete response ({len(holdings)} holdings)")
        except (
            KeyError,
            requests.RequestException,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as exc:
            errors.append(f"{url}: {exc}")

    try:
        response = _request(client, SP500_WIKIPEDIA_URL, timeout)
        holdings = parse_sp500_wikipedia_html(response.text)
        if _is_complete(holdings):
            return SourceResult(
                name="SPY",
                holdings=holdings,
                selected_source=SP500_WIKIPEDIA_URL,
                    as_of=measurement_date(),
                errors=errors,
            )
        errors.append(f"{SP500_WIKIPEDIA_URL}: incomplete response ({len(holdings)} holdings)")
    except (requests.RequestException, UnicodeError) as exc:
        errors.append(f"{SP500_WIKIPEDIA_URL}: {exc}")

    return SourceResult(name="SPY", errors=errors)
