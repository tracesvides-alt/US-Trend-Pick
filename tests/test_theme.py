from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from engine.theme.classifier import (
    classify_company,
    fetch_company_profiles,
    load_theme_master,
    run_theme_classifier,
)
from engine.theme.history import (
    load_theme_snapshot,
    stabilize_classifications,
    update_theme_history,
    write_theme_artifacts,
)
from engine.theme.models import CompanyProfile, ThemeClassification, ThemeHistoryRecord, ThemeRunResult


def _definitions():
    return load_theme_master()


def test_theme_master_contains_only_fixed_classifier_names() -> None:
    definitions = _definitions()
    names = {definition.name for definition in definitions}

    assert "AI Memory / HBM" in names
    assert "AI Cloud / Compute Infrastructure" in names
    assert "Enterprise Software / AI Software" in names
    assert "Other" in names
    assert len(names) == 27


@pytest.mark.parametrize(
    ("ticker", "profile", "expected_theme"),
    [
        (
            "LITE",
            CompanyProfile(
                ticker="LITE",
                sector="Technology",
                industry="Communication Equipment",
                product_service="Optical transceivers and coherent optical components",
                business_summary="Photonics and optical communication products",
            ),
            "Optical / Photonics",
        ),
        (
            "COHR",
            CompanyProfile(
                ticker="COHR",
                sector="Technology",
                industry="Communication Equipment",
                product_service="Lasers, photonics, optical components, and transceivers",
                business_summary="Optical communications and coherent photonics",
            ),
            "Optical / Photonics",
        ),
        (
            "CRWD",
            CompanyProfile(
                ticker="CRWD",
                sector="Technology",
                industry="Software - Infrastructure",
                product_service="Endpoint security and threat detection platform",
                business_summary="Cybersecurity, threat intelligence, and security operations",
            ),
            "Cybersecurity",
        ),
        (
            "CRDO",
            CompanyProfile(
                ticker="CRDO",
                sector="Technology",
                industry="Semiconductors",
                product_service="Networking silicon, SerDes, Ethernet connectivity, and DSP",
                business_summary="High-speed interconnect and data center networking solutions",
            ),
            "AI Networking",
        ),
        (
            "MU",
            CompanyProfile(
                ticker="MU",
                sector="Technology",
                industry="Semiconductors",
                product_service="DRAM, HBM, and AI memory chips",
                business_summary="Memory and storage products including DRAM and NAND",
            ),
            "AI Memory / HBM",
        ),
        (
            "SNDK",
            CompanyProfile(
                ticker="SNDK",
                sector="Technology",
                industry="Data Storage",
                product_service="NAND flash memory and solid-state drives",
                business_summary="Data storage and flash memory solutions",
            ),
            "NAND / Storage",
        ),
        (
            "NBIS",
            CompanyProfile(
                ticker="NBIS",
                sector="Technology",
                industry="Cloud Computing",
                product_service="GPU cloud, AI compute capacity, and GPU-as-a-Service",
                business_summary="AI cloud platform for hyperscale compute infrastructure",
            ),
            "AI Cloud / Compute Infrastructure",
        ),
        (
            "VRT",
            CompanyProfile(
                ticker="VRT",
                sector="Industrials",
                industry="Electrical Equipment & Parts",
                product_service="Data center power distribution, UPS, thermal management, and cooling",
                business_summary="Power and cooling systems for critical digital infrastructure",
            ),
            "Data Center Power / Cooling",
        ),
    ],
)
def test_classification_sanity_fixture(ticker, profile, expected_theme) -> None:
    result = classify_company(profile, _definitions(), date(2026, 8, 28))

    assert result.ticker == ticker
    assert result.primary_theme == expected_theme
    assert result.primary_theme != "AI Cloud / Compute Infrastructure" or ticker == "NBIS"
    assert result.theme_score > result.second_theme_score


def test_keyword_classifier_prefers_high_priority_profile_evidence() -> None:
    result = classify_company(
        CompanyProfile(
            ticker="CRDO",
            company_name="Connectivity Example",
            sector="Technology",
            industry="Semiconductors",
            business_summary="Ethernet SerDes connectivity and data center interconnect",
        ),
        _definitions(),
        date(2026, 8, 28),
    )

    assert result.primary_theme == "AI Networking"
    assert result.theme_score > result.second_theme_score
    assert result.proposed_theme == result.primary_theme
    assert result.confidence in {"HIGH", "MEDIUM", "LOW"}


def test_generic_ai_cloud_end_market_terms_do_not_create_cloud_theme() -> None:
    result = classify_company(
        CompanyProfile(
            ticker="GENERIC",
            sector="Technology",
            industry="Software - Infrastructure",
            business_summary=(
                "A digital transformation platform serving AI, cloud, data center, "
                "and infrastructure customers"
            ),
            end_market="AI cloud infrastructure demand",
        ),
        _definitions(),
        date(2026, 8, 28),
    )

    assert result.primary_theme == "Enterprise Software / AI Software"
    assert result.primary_theme != "AI Cloud / Compute Infrastructure"


def test_product_service_signal_beats_generic_end_market_signal() -> None:
    result = classify_company(
        CompanyProfile(
            ticker="PRODUCT",
            sector="Technology",
            industry="Communication Equipment",
            product_service="Optical transceivers and coherent photonics",
            business_summary="Serves AI cloud data center infrastructure demand",
            end_market="AI cloud infrastructure",
        ),
        _definitions(),
        date(2026, 8, 28),
    )

    assert result.primary_theme == "Optical / Photonics"


def test_sector_industry_fallback_and_other_are_master_values() -> None:
    financial = classify_company(
        CompanyProfile(ticker="BANK", industry="Banks - Regional"),
        _definitions(),
        date(2026, 8, 28),
    )
    unknown = classify_company(
        CompanyProfile(ticker="UNKNOWN", company_name="Unclear Holdings"),
        _definitions(),
        date(2026, 8, 28),
    )

    assert financial.primary_theme == "Financials"
    assert unknown.primary_theme == "Other"
    assert unknown.theme_score == 100.0


def test_profile_download_is_mockable_and_uses_universe_fallback(tmp_path) -> None:
    universe = pd.DataFrame(
        [{"ticker": "AAA", "company_name": "Example Corp", "sector": "Energy"}]
    )

    def fake_fetcher(ticker: str) -> CompanyProfile:
        return CompanyProfile(ticker=ticker, industry="Oil & Gas E&P")

    profiles, failures = fetch_company_profiles(
        ["AAA"], universe, tmp_path / "profiles.json", fetcher=fake_fetcher
    )

    assert failures == {}
    assert profiles["AAA"].company_name == "Example Corp"
    assert profiles["AAA"].sector == "Energy"
    assert profiles["AAA"].industry == "Oil & Gas E&P"


def test_legacy_profile_cache_is_refreshed_after_classifier_schema_change(tmp_path) -> None:
    cache_path = tmp_path / "profiles.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "ticker": "AAA",
                    "company_name": "Example Corp",
                    "sector": "Technology",
                    "industry": "Software - Infrastructure",
                    "business_summary": "Old cached summary",
                }
            ]
        ),
        encoding="utf-8",
    )
    universe = pd.DataFrame([{"ticker": "AAA"}])
    calls: list[str] = []

    def fake_fetcher(ticker: str) -> CompanyProfile:
        calls.append(ticker)
        return CompanyProfile(
            ticker=ticker,
            product_service="Endpoint security",
            sector="Technology",
            industry="Software - Infrastructure",
            business_summary="Security software",
        )

    profiles, failures = fetch_company_profiles(
        ["AAA"], universe, cache_path, fetcher=fake_fetcher
    )

    assert failures == {}
    assert calls == ["AAA"]
    assert profiles["AAA"].product_service == "Endpoint security"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2


def _classification(
    ticker: str,
    primary: str,
    proposed: str,
    as_of: date,
) -> ThemeClassification:
    scores = {primary: 60.0, proposed: 90.0}
    return ThemeClassification(
        ticker=ticker,
        primary_theme=primary,
        theme_score=scores[primary],
        second_theme=proposed,
        second_theme_score=scores[proposed],
        confidence="HIGH",
        as_of=as_of,
        proposed_theme=proposed,
        proposed_theme_score=scores[proposed],
        theme_scores=scores,
    )


def test_theme_change_requires_two_consecutive_snapshots() -> None:
    old = ThemeHistoryRecord(
        ticker="AAA",
        primary_theme="Energy",
        effective_from=date(2026, 8, 1),
    )
    prior = _classification("AAA", "Energy", "AI Networking", date(2026, 8, 22))
    current = _classification("AAA", "AI Networking", "AI Networking", date(2026, 8, 29))

    held = stabilize_classifications([prior], [old], {}, date(2026, 8, 22))[0]
    changed = stabilize_classifications([current], [old], {"AAA": held}, date(2026, 8, 29))[0]

    assert held.primary_theme == "Energy"
    assert held.change_reason == "STABILITY_HOLD"
    assert changed.primary_theme == "AI Networking"
    assert changed.theme_changed is True

    history, changes = update_theme_history([old], [changed], date(2026, 8, 29))
    assert [(row.primary_theme, row.effective_to) for row in history] == [
        ("Energy", date(2026, 8, 28)),
        ("AI Networking", None),
    ]
    assert changes[0].previous_theme == "Energy"
    assert changes[0].new_theme == "AI Networking"


def test_legacy_broad_cloud_assignment_is_reclassified_immediately() -> None:
    old = ThemeHistoryRecord(
        ticker="LITE",
        primary_theme="Cloud / AI Infrastructure",
        effective_from=date(2026, 8, 1),
    )
    current = _classification(
        "LITE", "Optical / Photonics", "Optical / Photonics", date(2026, 8, 29)
    )

    fixed = stabilize_classifications([current], [old], {}, date(2026, 8, 29))[0]

    assert fixed.primary_theme == "Optical / Photonics"
    assert fixed.theme_changed is True
    assert fixed.change_reason == "LEGACY_THEME_RECLASSIFICATION"


def test_theme_snapshot_is_point_in_time_and_history_is_persisted(tmp_path) -> None:
    as_of = date(2026, 8, 28)
    row = _classification("AAA", "Other", "Other", as_of)
    result = ThemeRunResult(as_of=as_of, classifications=[row], history=[], changes=[])
    paths = write_theme_artifacts(result, tmp_path)

    assert paths["snapshot"].name == "2026-08-28.json"
    assert load_theme_snapshot(paths["snapshot"])[0].as_of == as_of
    assert json.loads(paths["history"].read_text(encoding="utf-8")) == []


def test_theme_classifier_runs_after_tactical_and_writes_same_date_snapshot(tmp_path) -> None:
    tactical_path = tmp_path / "tactical-2026-08-28.csv"
    universe_path = tmp_path / "2026-08-28.csv"
    pd.DataFrame([{"ticker": "AAA", "tactical_rank": 1}]).to_csv(
        tactical_path, index=False
    )
    pd.DataFrame([{"ticker": "AAA", "company_name": "Bank Example"}]).to_csv(
        universe_path, index=False
    )

    result, paths = run_theme_classifier(
        tactical_path=tactical_path,
        universe_path=universe_path,
        theme_dir=tmp_path / "themes",
        as_of=date(2026, 8, 28),
        profile_fetcher=lambda ticker: CompanyProfile(
            ticker=ticker, industry="Banks - Regional"
        ),
    )

    assert result.classifications[0].primary_theme == "Financials"
    assert paths["snapshot"].name == "2026-08-28.json"
    assert load_theme_snapshot(paths["snapshot"])[0].primary_theme == "Financials"
