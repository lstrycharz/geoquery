"""Bootstrap script for the regression dataset (smoke tier).

This test is marked `regression_record` and is excluded from the default test
run (see pyproject.toml's `addopts`). To populate or refresh the bootstrap
case, run:

    pytest -m regression_record

It wraps the existing FakeAnthropicClient in a RecordingCassetteClient,
exercises the full agent pipeline once per case, and writes the resulting
{cassette,input,expected}.json triple to regression_dataset/<slug>/.

When you want REAL LLM responses (instead of fake-cassette responses), swap
the inner client for a real Anthropic instance. The recording protocol is the
same; only the inner client differs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import run_brief
from evals.regression import REGRESSION_DATASET_DIR, RecordingCassetteClient
from tests.test_agent_e2e import _PIPELINE_CASSETTES

# (slug, company, market). Add cases here; the smoke tier pulls from this list.
_SMOKE_CASES: tuple[tuple[str, str, str], ...] = (
    ("notion_b2b_saas", "Notion", "B2B SaaS knowledge management"),
)


@pytest.mark.regression_record
@pytest.mark.parametrize("slug,company,market", _SMOKE_CASES)
def test_record_smoke_case(fake_client, tmp_settings, stub_embedder, slug, company, market):
    """Run the pipeline with a recording client; persist the cassette + baseline."""
    for cassette_name in _PIPELINE_CASSETTES:
        fake_client.load_cassette(cassette_name)
    recorder = RecordingCassetteClient(inner=fake_client)

    outcome = run_brief(
        company=company,
        market=market,
        settings=tmp_settings,
        client=recorder,
        embedder=stub_embedder,
        fetch_page=lambda url: None,
    )
    assert outcome.status == "completed", outcome.error

    from memory import EpisodicMemory

    mem = EpisodicMemory(db_path=tmp_settings.data_dir / "episodic.db")
    invocations = mem.get_invocations(outcome.run_id)
    eval_profile = {i["skill_name"]: bool(i["eval_passed"]) for i in invocations}

    case_dir = REGRESSION_DATASET_DIR / slug
    case_dir.mkdir(parents=True, exist_ok=True)
    recorder.dump(case_dir / "cassette.json")
    (case_dir / "input.json").write_text(
        json.dumps({"company": company, "market": market, "sitemap_url": None}, indent=2),
        encoding="utf-8",
    )
    (case_dir / "expected.json").write_text(
        json.dumps(
            {
                "eval_profile": eval_profile,
                "status": outcome.status,
                "notes": (
                    "Baseline captured from FakeAnthropicClient cassettes — replace with "
                    "real-LLM recording (see EVALS.md) to enable real-prompt regression."
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


@pytest.mark.regression_record
def test_record_writes_files_under_dataset_dir():
    """Sanity check: after the recording pass, the dataset dir is populated."""
    for slug, _, _ in _SMOKE_CASES:
        case_dir = REGRESSION_DATASET_DIR / slug
        for f in ("cassette.json", "input.json", "expected.json"):
            assert (case_dir / f).is_file(), f"missing {case_dir / f}"


def test_record_test_is_excluded_from_default_run():
    """Defense-in-depth: the marker must be in `addopts` deselect list. If a
    future contributor removes that, this test catches it loudly."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    src = pyproject.read_text()
    # The default pytest run should deselect `regression_record`.
    assert "regression_record" in src
    assert "-m" in src and "not regression_record" in src
