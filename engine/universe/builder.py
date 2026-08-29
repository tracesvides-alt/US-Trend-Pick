"""Build and persist the integrated SPY/QQQ/QQQJ universe."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
import requests
import yaml

from engine.dates import measurement_date
from engine.universe.models import Holding, SourceResult, UniverseBuildReport, UniverseMember
from engine.universe.qqq import fetch_qqq_holdings
from engine.universe.qqqj import fetch_qqqj_holdings
from engine.universe.spy import fetch_spy_holdings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIAS_PATH = REPO_ROOT / "config" / "ticker_alias.yaml"
DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "data" / "universe"
EXCLUDED_TICKERS = {
    "CASH",
    "USD",
    "FUTURE",
    "FUTURES",
    "ETF",
    "-",
    "--",
    "SPY",
    "QQQ",
    "QQQJ",
    "N/A",
    "NA",
    "NONE",
    "NAN",
}


def load_ticker_aliases(path: str | Path = DEFAULT_ALIAS_PATH) -> dict[str, str]:
    """Load vendor ticker aliases from YAML."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    aliases = raw.get("aliases", raw) if isinstance(raw, Mapping) else {}
    if not isinstance(aliases, Mapping):
        raise ValueError(f"Ticker alias configuration must be a mapping: {path}")
    return {str(key).strip().upper(): str(value).strip().upper() for key, value in aliases.items()}


def normalize_ticker(ticker: str, aliases: Mapping[str, str] | None = None) -> str:
    """Normalize common vendor forms while preserving the security symbol."""
    normalized = str(ticker).strip().upper().replace("$", "")
    normalized = normalized.replace(" ", "")
    if ":" in normalized:
        normalized = normalized.rsplit(":", 1)[-1]
    normalized = normalized.removesuffix(".US")
    normalized = (aliases or {}).get(normalized, normalized)
    return normalized


def _is_excluded(ticker: str, company_name: str) -> bool:
    upper_ticker = ticker.upper()
    upper_name = company_name.upper()
    if upper_ticker in EXCLUDED_TICKERS or not upper_ticker:
        return True
    if any(token in upper_ticker for token in ("FUTURE", "ETF", "CASH")):
        return True
    if upper_name.startswith("USD ") or upper_name in {"US DOLLAR", "CASH"}:
        return True
    if any(
        token in upper_name
        for token in ("MONEY MARKET", "FUTURES", "CASH", "ETF", "CONTRA", "SWAP", "FORWARD")
    ):
        return True
    if upper_ticker.startswith("^") or upper_ticker.startswith("#"):
        return True
    return False


def _normalized_holdings(
    holdings: Iterable[Holding],
    aliases: Mapping[str, str],
) -> list[Holding]:
    unique: dict[str, Holding] = {}
    for holding in holdings:
        ticker = normalize_ticker(holding.ticker, aliases)
        name = holding.company_name.strip()
        if _is_excluded(ticker, name) or ticker in unique:
            continue
        unique[ticker] = Holding(ticker=ticker, company_name=name)
    return list(unique.values())


def merge_universes(
    spy: SourceResult,
    qqq: SourceResult,
    qqqj: SourceResult,
    as_of: date | None = None,
    aliases: Mapping[str, str] | None = None,
) -> tuple[list[UniverseMember], int]:
    """Union three source results and return members plus duplicate row count."""
    snapshot_date = as_of or measurement_date()
    alias_map = aliases or {}
    source_rows = (
        ("source_spy", spy),
        ("source_qqq", qqq),
        ("source_qqqj", qqqj),
    )
    members: dict[str, UniverseMember] = {}
    total_rows = 0
    for source_field, result in source_rows:
        cleaned = _normalized_holdings(result.holdings, alias_map)
        total_rows += len(cleaned)
        for holding in cleaned:
            if holding.ticker not in members:
                members[holding.ticker] = UniverseMember(
                    ticker=holding.ticker,
                    company_name=holding.company_name,
                    as_of=snapshot_date,
                )
            members[holding.ticker] = members[holding.ticker].model_copy(
                update={source_field: True}
            )
    ordered = [members[ticker] for ticker in sorted(members)]
    return ordered, total_rows - len(ordered)


def write_snapshot(
    members: Iterable[UniverseMember],
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    as_of: date | None = None,
) -> Path:
    """Write a deterministic CSV snapshot named by its as-of date."""
    snapshot_date = as_of or measurement_date()
    output_dir = Path(snapshot_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{snapshot_date.isoformat()}.csv"
    columns = [
        "ticker",
        "company_name",
        "source_spy",
        "source_qqq",
        "source_qqqj",
        "as_of",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for member in sorted(members, key=lambda item: item.ticker):
            writer.writerow(
                {
                    "ticker": member.ticker,
                    "company_name": member.company_name,
                    "source_spy": member.source_spy,
                    "source_qqq": member.source_qqq,
                    "source_qqqj": member.source_qqqj,
                    "as_of": member.as_of.isoformat(),
                }
            )
    return output_path


def build_universe(
    session: requests.Session | None = None,
    as_of: date | None = None,
    alias_path: str | Path = DEFAULT_ALIAS_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
) -> UniverseBuildReport:
    """Acquire all three universes, merge them, and write a complete snapshot."""
    client = session or requests.Session()
    snapshot_date = as_of or measurement_date()
    aliases = load_ticker_aliases(alias_path)
    spy = fetch_spy_holdings(client)
    qqq = fetch_qqq_holdings(client)
    qqqj = fetch_qqqj_holdings(client)
    results = (spy, qqq, qqqj)
    failed = [result.name for result in results if not result.succeeded]
    if failed:
        details = "; ".join(
            f"{result.name}: {', '.join(result.errors) or 'no complete source'}"
            for result in results
            if not result.succeeded
        )
        raise RuntimeError(f"Complete universe acquisition failed ({details})")

    members, duplicate_removed = merge_universes(
        spy,
        qqq,
        qqqj,
        as_of=snapshot_date,
        aliases=aliases,
    )
    output_path = write_snapshot(members, snapshot_dir=snapshot_dir, as_of=snapshot_date)
    return UniverseBuildReport(
        spy=spy,
        qqq=qqq,
        qqqj=qqqj,
        members=members,
        duplicate_removed=duplicate_removed,
        snapshot_path=str(output_path),
    )


def _print_report(report: UniverseBuildReport) -> None:
    print(f"SPY件数: {len(report.spy.holdings)}")
    print(f"QQQ件数: {len(report.qqq.holdings)}")
    print(f"QQQJ件数: {len(report.qqqj.holdings)}")
    print(f"Union後件数: {len(report.members)}")
    print(f"重複除去件数: {report.duplicate_removed}")
    for result in (report.spy, report.qqq, report.qqqj):
        print(f"{result.name} source: {result.selected_source}")
        if result.errors:
            print(f"{result.name} failed sources:")
            for error in result.errors:
                print(f"  - {error}")
    print(f"Snapshot: {report.snapshot_path}")


if __name__ == "__main__":
    _print_report(build_universe())
