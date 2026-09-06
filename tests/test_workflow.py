import json
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "weekly-ranking.yml"
MOMENTUM_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "momentum-overview.yml"


def test_weekly_workflow_is_valid_yaml_and_has_requested_schedule() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    assert 'cron: "17 23 * * 5"' in text
    assert "workflow_dispatch:" in text


def test_weekly_workflow_runs_pipeline_in_order_and_deploys_after_checks() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    steps = [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "name: Install Python dependencies",
        "name: Restore Cache",
        "name: Universe",
        "name: Market Data",
        "name: Validation",
        "name: Base",
        "name: Regime",
        "name: Tactical",
        "name: Theme",
        "name: Portfolio",
        "name: Generate JSON",
        "name: pytest",
        "name: ruff",
        "name: Node Setup",
        "name: Frontend Build",
        "name: Vercel Deploy",
        "name: Save Cache",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "python -m engine.universe.builder" in text
    assert "python -m engine.market_data.cache" in text
    assert "python -m engine.results.builder" in text
    assert "python -m engine.theme.classifier" in text
    assert "test -s data/results/theme-review.json" in text
    assert "cp data/results/latest.json web/public/data/latest.json" in text
    assert "data/themes/history.json" in text
    assert "failure_count" in text
    assert "if: success()" in text
    assert 'cd "$GITHUB_WORKSPACE"' in text
    assert 'npx --yes vercel@latest pull' in text
    assert '--project="$VERCEL_PROJECT_ID"' in text
    assert "mkdir -p .vercel/output/static" in text
    assert "cp -R web/dist/. .vercel/output/static/" in text
    assert '{"version":3}' in text
    assert "test -s .vercel/output/static/index.html" in text
    assert "npx --yes vercel@latest build --prod" not in text
    assert "npx --yes vercel@latest deploy --prebuilt --prod" in text
    assert "VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}" in text
    assert "VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}" in text
    assert "VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}" in text
    deploy_start = text.index("- name: Vercel Deploy")
    deploy_block = text[deploy_start:text.index("- name: Pipeline Summary", deploy_start)]
    assert "if: success()" in deploy_block


def test_vercel_configuration_is_static_vite_without_functions() -> None:
    config_path = WORKFLOW.parents[2] / "web" / "vercel.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["framework"] == "vite"
    assert config["outputDirectory"] == "dist"
    assert "functions" not in config


def test_momentum_overview_workflow_waits_for_fresh_source_before_deploy() -> None:
    text = MOMENTUM_WORKFLOW.read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    assert 'cron: "15 21 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "MOMENTUM_MASTER_TOKEN" in text
    assert "repository: tracesvides-alt/momentum_master" in text
    assert "Wait for completed Momentum Master update" in text
    assert "actions/workflows/${SOURCE_WORKFLOW}/runs" in text
    assert "status=${run_status}" in text
    assert "last_updated.txt" in text
    assert "TZ=Asia/Tokyo date +%F" in text
    assert "古いキャッシュではDeployしません" in text
    assert "ref: ${{ steps.source.outputs.source_sha }}" in text
    assert "engine.integration.momentum_master" in text
    assert "test -s web/public/data/momentum-overview.json" in text
    assert "name: Frontend Build" in text
    assert "name: Vercel Deploy" in text
    deploy_block = text[text.index("- name: Vercel Deploy") :]
    assert 'npx --yes vercel@latest deploy --prebuilt --prod' in deploy_block
