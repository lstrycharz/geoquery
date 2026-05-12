"""Bootstrap script for the regression dataset.

This test is marked `regression_record` and is excluded from the default test
run (see pyproject.toml's `addopts`). To populate or refresh ALL bootstrap
cases, run:

    pytest -m regression_record

Cassettes are bootstrapped against the existing FakeAnthropicClient (cheap,
deterministic, same fake response per skill regardless of input). The input
strings DO differ per slug (Company/Market), so the prompt-hashes differ and
each slug gets a unique cassette file. This exercises the harness across 30
parametrized cases without burning real-API spend.

The companion `test_regression_record_live.py` records REAL LLM responses
(~$0.50/case). It's a separate file with a `regression_record_live` marker so
spend is explicit.
"""

from __future__ import annotations

import pytest

from evals.regression import REGRESSION_DATASET_DIR, record_case_to_disk
from tests.test_agent_e2e import _PIPELINE_CASSETTES

# Smoke tier — pre-commit gate runs these.
# Same skill cassettes for all slugs (FakeAnthropicClient serves one response
# per skill name regardless of input), but the per-call prompt-hashes vary
# because Company/Market vary in the user messages.
_SMOKE_CASES: tuple[tuple[str, str, str], ...] = (
    ("notion_b2b_saas", "Notion", "B2B SaaS knowledge management"),
    ("linear_b2b_saas", "Linear", "B2B SaaS project management"),
    ("glossier_dtc_beauty", "Glossier", "DTC beauty"),
    ("stripe_payments", "Stripe", "payments infrastructure"),
    ("webflow_nocode", "Webflow", "no-code design platform"),
)

# Full tier — PR-CI runs smoke + full.
_FULL_CASES: tuple[tuple[str, str, str], ...] = (
    ("hubspot_smb_crm", "HubSpot", "small-business CRM"),
    ("vercel_frontend_cloud", "Vercel", "frontend cloud hosting"),
    ("patagonia_dtc_outdoor", "Patagonia", "DTC outdoor apparel"),
    ("shopify_ecommerce", "Shopify", "e-commerce platform for DTC brands"),
    ("canva_design", "Canva", "online graphic design for non-designers"),
    ("mailchimp_email", "Mailchimp", "email marketing for SMBs"),
    ("asana_pm", "Asana", "project management for marketing teams"),
    ("squarespace_websites", "Squarespace", "all-in-one website builder"),
    ("typeform_forms", "Typeform", "conversational form builder"),
    ("miro_whiteboard", "Miro", "collaborative whiteboard for distributed teams"),
    ("figma_design", "Figma", "collaborative product design tool"),
    ("zoom_video", "Zoom", "video conferencing for enterprise"),
    ("slack_messaging", "Slack", "team messaging for engineering orgs"),
    ("atlassian_devtools", "Atlassian", "developer collaboration tools (Jira/Confluence)"),
    ("github_devplatform", "GitHub", "developer platform for source control + CI/CD"),
    ("allbirds_dtc_apparel", "Allbirds", "DTC sustainable footwear"),
    ("warby_parker_dtc_eyewear", "Warby Parker", "DTC eyewear"),
    ("casper_dtc_mattress", "Casper", "DTC sleep brand"),
    ("peloton_fitness", "Peloton", "connected home fitness"),
    ("duolingo_edtech", "Duolingo", "mobile language learning"),
    ("coursera_edtech", "Coursera", "online learning platform"),
    ("teladoc_healthtech", "Teladoc", "telehealth services"),
    ("one_medical_healthtech", "One Medical", "primary care subscription"),
    ("airbnb_marketplace", "Airbnb", "vacation rental marketplace"),
    ("doordash_marketplace", "DoorDash", "on-demand food delivery"),
)

_ALL_CASES: tuple[tuple[str, str, str, str], ...] = tuple(
    [(s, c, m, "smoke") for s, c, m in _SMOKE_CASES]
    + [(s, c, m, "full") for s, c, m in _FULL_CASES]
)


@pytest.mark.regression_record
@pytest.mark.parametrize("slug,company,market,tier", _ALL_CASES)
def test_record_case(fake_client, tmp_settings, stub_embedder, slug, company, market, tier):
    """Record one bootstrap case with the FakeAnthropicClient as inner."""
    for cassette_name in _PIPELINE_CASSETTES:
        fake_client.load_cassette(cassette_name)
    record_case_to_disk(
        slug=slug,
        company=company,
        market=market,
        tier=tier,
        source="bootstrap-fake-client",
        client=fake_client,
        settings=tmp_settings,
        embedder=stub_embedder,
        fetch_page=lambda url: None,
    )


@pytest.mark.regression_record
def test_record_writes_files_under_dataset_dir():
    """Sanity check: after the recording pass, the dataset dir is populated."""
    for slug, _, _, _ in _ALL_CASES:
        case_dir = REGRESSION_DATASET_DIR / slug
        for f in ("cassette.json", "input.json", "expected.json"):
            assert (case_dir / f).is_file(), f"missing {case_dir / f}"


def test_record_test_is_excluded_from_default_run():
    """The marker must be in `addopts` deselect list. If a future contributor
    removes that, this test catches it loudly."""
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    src = pyproject.read_text()
    assert "regression_record" in src
    assert "not regression_record" in src


def test_smoke_and_full_lists_are_disjoint():
    """Defense-in-depth: a slug can only live in one tier."""
    smoke_slugs = {s for s, _, _ in _SMOKE_CASES}
    full_slugs = {s for s, _, _ in _FULL_CASES}
    assert smoke_slugs.isdisjoint(full_slugs)
    assert len(smoke_slugs) == len(_SMOKE_CASES)
    assert len(full_slugs) == len(_FULL_CASES)


def test_total_case_count_matches_plan_target():
    """Plan targets 30+ cases for the full regression suite."""
    total = len(_SMOKE_CASES) + len(_FULL_CASES)
    assert total >= 30, f"need at least 30 cases for the full tier, have {total}"
