"""Automatic Primary Theme classifier executed after Tactical Ranking."""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml
import yfinance as yf

from engine.dates import measurement_date
from engine.theme.history import (
    DEFAULT_THEME_DIR,
    active_theme_history_map,
    load_theme_history,
    latest_theme_snapshot_map,
    stabilize_classifications,
    update_theme_history,
    write_theme_artifacts,
)
from engine.theme.keywords import (
    INDUSTRY_THEME_WEIGHTS,
    SECTOR_THEME_WEIGHTS,
    SOURCE_WEIGHTS,
    THEME_KEYWORDS,
    all_keyword_themes,
)
from engine.theme.models import (
    CompanyProfile,
    ThemeDefinition,
    ThemeClassification,
    ThemeRunResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config" / "themes.yaml"
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_PROFILE_CACHE_PATH = DEFAULT_THEME_DIR / "company-profiles.json"
DEFAULT_TACTICAL_DIR = DEFAULT_RESULTS_DIR
PROFILE_WORKERS = 8


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _norm(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def load_theme_master(
    path: str | Path = DEFAULT_CATALOG_PATH,
) -> list[ThemeDefinition]:
    """Load the fixed catalog and reject classifier names outside the master."""

    catalog_path = Path(path)
    if not catalog_path.exists():
        raise FileNotFoundError(f"Theme Master not found: {catalog_path}")
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    rows = payload.get("themes", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("themes.yaml must contain a themes list")

    definitions: list[ThemeDefinition] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if isinstance(row, str):
            definition = ThemeDefinition(name=row.strip())
        elif isinstance(row, dict):
            definition = ThemeDefinition.model_validate(row)
        else:
            raise ValueError(f"themes.yaml record {index} must be a string or mapping")
        key = definition.name.casefold()
        if key in seen:
            raise ValueError(f"duplicate Primary Theme in themes.yaml: {definition.name}")
        seen.add(key)
        definitions.append(definition)

    missing = sorted(all_keyword_themes() - {item.name for item in definitions})
    if missing:
        raise ValueError(
            "Theme Master is missing classifier Themes: " + ", ".join(missing)
        )
    return definitions


def _catalog_map(definitions: list[ThemeDefinition]) -> dict[str, ThemeDefinition]:
    return {definition.name.casefold(): definition for definition in definitions}


def _profile_from_row(row: Any, ticker: str) -> CompanyProfile:
    values = row.to_dict() if isinstance(row, pd.Series) else dict(row or {})
    return CompanyProfile(
        ticker=ticker,
        company_name=_text(
            values.get("company_name")
            or values.get("longName")
            or values.get("shortName")
        )
        or None,
        sector=_text(values.get("sector")) or None,
        industry=_text(values.get("industry")) or None,
        business_summary=_text(
            values.get("business_summary") or values.get("longBusinessSummary")
        )
        or None,
    )


def _profile_from_yahoo(ticker: str) -> CompanyProfile:
    yahoo_ticker = yf.Ticker(ticker)
    get_info = getattr(yahoo_ticker, "get_info", None)
    info = get_info() if callable(get_info) else yahoo_ticker.info
    if not isinstance(info, dict):
        info = {}
    return CompanyProfile(
        ticker=ticker,
        company_name=_text(info.get("longName") or info.get("shortName")) or None,
        sector=_text(info.get("sector")) or None,
        industry=_text(info.get("industry")) or None,
        business_summary=_text(info.get("longBusinessSummary")) or None,
    )


def _load_profile_cache(path: str | Path) -> dict[str, CompanyProfile]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [dict(value, ticker=key) for key, value in payload.items()]
    else:
        raise ValueError("company profile cache must be a list or mapping")
    return {
        row.ticker: row
        for row in (CompanyProfile.model_validate(item) for item in rows)
    }


def _save_profile_cache(
    profiles: dict[str, CompanyProfile],
    path: str | Path,
) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(f".{cache_path.name}.tmp")
    temporary.write_text(
        json.dumps(
            [profile.model_dump(mode="json") for profile in profiles.values()],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)


def fetch_company_profiles(
    tickers: list[str],
    universe: pd.DataFrame,
    cache_path: str | Path = DEFAULT_PROFILE_CACHE_PATH,
    fetcher: Callable[[str], CompanyProfile] | None = None,
    max_workers: int = PROFILE_WORKERS,
) -> tuple[dict[str, CompanyProfile], dict[str, str]]:
    """Load cached/free Yahoo profiles and fetch missing fields in parallel."""

    cached = _load_profile_cache(cache_path)
    universe_rows = {
        str(row.get("ticker", "")).strip().upper(): row
        for row in universe.to_dict("records")
        if str(row.get("ticker", "")).strip()
    }
    profiles: dict[str, CompanyProfile] = {}
    for ticker in tickers:
        base = _profile_from_row(universe_rows.get(ticker, {}), ticker)
        previous = cached.get(ticker)
        if previous is not None:
            base = base.model_copy(
                update={
                    "company_name": base.company_name or previous.company_name,
                    "sector": base.sector or previous.sector,
                    "industry": base.industry or previous.industry,
                    "business_summary": base.business_summary or previous.business_summary,
                }
            )
        profiles[ticker] = base

    get_profile = fetcher or _profile_from_yahoo
    pending = [
        ticker
        for ticker, profile in profiles.items()
        if not profile.sector or not profile.industry or not profile.business_summary
    ]
    failures: dict[str, str] = {}
    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(get_profile, ticker): ticker for ticker in pending}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    fetched = future.result()
                    if not isinstance(fetched, CompanyProfile):
                        fetched = CompanyProfile.model_validate(fetched)
                    current = profiles[ticker]
                    profiles[ticker] = current.model_copy(
                        update={
                            "company_name": fetched.company_name or current.company_name,
                            "sector": fetched.sector or current.sector,
                            "industry": fetched.industry or current.industry,
                            "business_summary": fetched.business_summary
                            or current.business_summary,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - one profile must not stop the run
                    failures[ticker] = f"{type(exc).__name__}: {exc}"
    _save_profile_cache(profiles, cache_path)
    return profiles, failures


def _add_mapping_scores(
    scores: dict[str, float],
    mapping: dict[str, dict[str, float]],
    text: str,
    source: str,
) -> None:
    normalized = _norm(text)
    if not normalized:
        return
    for phrase, theme_weights in mapping.items():
        if phrase in normalized:
            source_weight = SOURCE_WEIGHTS[source]
            for theme, weight in theme_weights.items():
                scores[theme] += weight * source_weight


def _confidence(
    top_score: float,
    second_score: float,
    evidence_count: int,
) -> str:
    gap = top_score - second_score
    if evidence_count >= 2 and top_score >= 70 and gap >= 25:
        return "HIGH"
    if evidence_count >= 1 and top_score >= 40 and gap >= 10:
        return "MEDIUM"
    return "LOW"


def classify_company(
    profile: CompanyProfile,
    definitions: list[ThemeDefinition],
    as_of: Any,
    previous_theme: str | None = None,
) -> ThemeClassification:
    """Score every master Theme using profile fields in priority order."""

    names = [definition.name for definition in definitions]
    scores = {name: 0.0 for name in names}
    hits: dict[str, list[str]] = {}
    fields = {
        "sector": profile.sector,
        "industry": profile.industry,
        "business_summary": profile.business_summary,
        "company_name": profile.company_name,
    }
    for source, value in fields.items():
        normalized = _norm(value)
        if not normalized:
            continue
        for theme, keywords in THEME_KEYWORDS.items():
            for keyword, weight in keywords.items():
                if _norm(keyword) in normalized:
                    scores[theme] += weight * SOURCE_WEIGHTS[source]
                    hits.setdefault(theme, []).append(f"{source}:{keyword}")
    _add_mapping_scores(scores, SECTOR_THEME_WEIGHTS, profile.sector or "", "sector")
    _add_mapping_scores(scores, INDUSTRY_THEME_WEIGHTS, profile.industry or "", "industry")

    # The previous result is a weak prior, never a new Theme and never strong
    # enough to defeat clear current profile evidence.
    previous_canonical = next(
        (name for name in names if previous_theme and name.casefold() == previous_theme.casefold()),
        None,
    )
    if previous_canonical:
        scores[previous_canonical] += 0.5
        hits.setdefault(previous_canonical, []).append("history:previous_theme")

    evidence = sum(score for score in scores.values())
    if evidence <= 0:
        other = next((name for name in names if name == "Other"), names[-1])
        scores[other] = 1.0
        hits.setdefault(other, []).append("fallback:Other")

    max_raw = max(scores.values())
    normalized_scores = {
        theme: round(max(0.0, min(100.0, score / max_raw * 100.0)), 6)
        for theme, score in scores.items()
    }
    order = {name: index for index, name in enumerate(names)}
    ranked = sorted(
        normalized_scores.items(), key=lambda item: (-item[1], order[item[0]])
    )
    primary, primary_score = ranked[0]
    second, second_score = ranked[1] if len(ranked) > 1 else (primary, 0.0)
    evidence_count = sum(len(values) for values in hits.values())
    return ThemeClassification(
        ticker=profile.ticker,
        primary_theme=primary,
        theme_score=primary_score,
        second_theme=second,
        second_theme_score=second_score,
        confidence=_confidence(primary_score, second_score, evidence_count),
        company_name=profile.company_name,
        sector=profile.sector,
        industry=profile.industry,
        as_of=as_of,
        proposed_theme=primary,
        proposed_theme_score=primary_score,
        keyword_hits=hits,
        theme_scores=normalized_scores,
    )


def _latest_file(directory: str | Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} found in {directory}")
    return files[-1]


def run_theme_classifier(
    tactical_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    catalog_path: str | Path = DEFAULT_CATALOG_PATH,
    theme_dir: str | Path = DEFAULT_THEME_DIR,
    profile_cache_path: str | Path | None = None,
    as_of: Any | None = None,
    profile_fetcher: Callable[[str], CompanyProfile] | None = None,
) -> tuple[ThemeRunResult, dict[str, Path]]:
    """Classify the completed Tactical snapshot and persist all Theme state."""

    output_date = as_of or measurement_date()
    tactical_file = Path(tactical_path) if tactical_path else _latest_file(
        DEFAULT_TACTICAL_DIR, "tactical-*.csv"
    )
    universe_file = Path(universe_path) if universe_path else _latest_file(
        DEFAULT_UNIVERSE_DIR, "*.csv"
    )
    tactical = pd.read_csv(tactical_file)
    universe = pd.read_csv(universe_file)
    definitions = load_theme_master(catalog_path)
    universe_tickers = {
        str(ticker).strip().upper()
        for ticker in universe.get("ticker", pd.Series(dtype=str)).dropna()
        if str(ticker).strip()
    }
    tactical_tickers = {
        str(ticker).strip().upper()
        for ticker in tactical.get("ticker", pd.Series(dtype=str)).dropna()
        if str(ticker).strip()
    }
    tickers = sorted(universe_tickers | tactical_tickers)
    cache_path = Path(profile_cache_path) if profile_cache_path else Path(theme_dir) / "company-profiles.json"
    profiles, profile_failures = fetch_company_profiles(
        tickers,
        universe,
        cache_path=cache_path,
        fetcher=profile_fetcher,
    )
    history = load_theme_history(Path(theme_dir) / "history.json")
    active = active_theme_history_map(history, output_date)
    prior_snapshots = latest_theme_snapshot_map(theme_dir, before=output_date)
    rank_map = {
        str(row.get("ticker", "")).strip().upper(): row.get("tactical_rank")
        for row in tactical.to_dict("records")
    }

    ordered_tickers = sorted(
        tickers,
        key=lambda ticker: (
            not _finite(rank_map.get(ticker)),
            float(rank_map.get(ticker)) if _finite(rank_map.get(ticker)) else float("inf"),
            ticker,
        ),
    )
    raw = [
        classify_company(
            profiles.get(ticker, CompanyProfile(ticker=ticker)),
            definitions,
            output_date,
            active.get(ticker).primary_theme if ticker in active else None,
        )
        for ticker in ordered_tickers
    ]
    classifications = stabilize_classifications(raw, history, prior_snapshots, output_date)
    updated_history, changes = update_theme_history(history, classifications, output_date)
    result = ThemeRunResult(
        as_of=output_date,
        classifications=classifications,
        history=updated_history,
        changes=changes,
        profile_failures=profile_failures,
    )
    paths = write_theme_artifacts(result, theme_dir)
    return result, paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify Primary Themes after Tactical Ranking")
    parser.add_argument("--as-of", default=None, help="Output date in YYYY-MM-DD format")
    args = parser.parse_args()
    output_date = date.fromisoformat(args.as_of) if args.as_of else None
    result, paths = run_theme_classifier(as_of=output_date)
    counts: dict[str, int] = {}
    for row in result.classifications:
        counts[row.primary_theme] = counts.get(row.primary_theme, 0) + 1
    print(f"Theme snapshot: {paths['snapshot']}")
    print(f"Classified: {len(result.classifications)}")
    print(f"Profile failures: {len(result.profile_failures)}")
    print(f"Theme changes: {len(result.changes)}")
    print(f"Theme counts: {counts}")


if __name__ == "__main__":
    main()
