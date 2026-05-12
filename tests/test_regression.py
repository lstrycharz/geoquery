"""Regression suite — replays recorded cassettes deterministically and
asserts the resulting eval-outcome profile matches the recorded baseline.

Cases live under `regression_dataset/<slug>/` with three files:
- `input.json`       — {company, market, sitemap_url?}
- `cassette.json`    — sha256(sys+usr+model) → CassetteEntry
- `expected.json`    — {eval_profile: {skill_name: passed_bool}, status, ...}

The smoke tier runs in pre-commit (`pytest -m regression_smoke`). Re-record a
case with `pytest -m regression_record` after an intentional prompt change.

Each case is parametrized by directory name; adding a directory under
regression_dataset/ automatically picks it up here.
"""

from __future__ import annotations

import json

import pytest

from agent import run_brief
from evals.regression import REGRESSION_DATASET_DIR, RegressionCassetteClient
from memory import EpisodicMemory


def _discover_cases() -> list[str]:
    if not REGRESSION_DATASET_DIR.is_dir():
        return []
    cases: list[str] = []
    for child in sorted(REGRESSION_DATASET_DIR.iterdir()):
        if not child.is_dir():
            continue
        if all((child / f).is_file() for f in ("input.json", "cassette.json", "expected.json")):
            cases.append(child.name)
    return cases


@pytest.mark.regression_smoke
@pytest.mark.parametrize("slug", _discover_cases())
def test_regression_case_replays_to_recorded_eval_profile(
    slug: str, tmp_settings, stub_embedder
) -> None:
    case_dir = REGRESSION_DATASET_DIR / slug
    inputs = json.loads((case_dir / "input.json").read_text())
    expected = json.loads((case_dir / "expected.json").read_text())
    client = RegressionCassetteClient.load(case_dir / "cassette.json")

    outcome = run_brief(
        company=inputs["company"],
        market=inputs["market"],
        sitemap_url=inputs.get("sitemap_url"),
        settings=tmp_settings,
        client=client,
        embedder=stub_embedder,
        fetch_page=lambda url: None,
    )

    assert outcome.status == expected["status"], (
        f"[{slug}] run status drifted: got {outcome.status!r}, expected {expected['status']!r}; "
        f"error={outcome.error!r}"
    )

    mem = EpisodicMemory(db_path=tmp_settings.data_dir / "episodic.db")
    invocations = mem.get_invocations(outcome.run_id)
    actual_profile = {i["skill_name"]: bool(i["eval_passed"]) for i in invocations}
    expected_profile = expected["eval_profile"]

    flipped_to_fail = [
        s for s, p in actual_profile.items() if p is False and expected_profile.get(s)
    ]
    flipped_to_pass = [
        s for s, p in actual_profile.items() if p is True and expected_profile.get(s) is False
    ]
    assert not flipped_to_fail, (
        f"[{slug}] regression — skills that used to pass now fail: {flipped_to_fail}"
    )
    assert not flipped_to_pass, (
        f"[{slug}] unexpected pass — skills that used to fail now pass: {flipped_to_pass}. "
        "If intentional, re-record the case (`pytest -m regression_record`)."
    )


def test_regression_dataset_has_at_least_one_case():
    """If you delete every case directory the suite stops covering anything —
    catch that loudly."""
    cases = _discover_cases()
    assert cases, (
        "regression_dataset/ has no cases; bootstrap one via `pytest -m regression_record`"
    )


def test_regression_dataset_dir_path_is_resolvable():
    assert REGRESSION_DATASET_DIR.name == "regression_dataset"
    assert REGRESSION_DATASET_DIR.parent.name == "GEOQuery"


def test_replay_raises_stale_cassette_when_company_changes(tmp_settings, stub_embedder):
    """The whole point of prompt-hash keying: if a prompt input changes, the
    cassette lookup misses and the gate trips. Drive that here by feeding a
    different company than the recorded baseline."""
    from evals.regression import RegressionStaleCassetteError

    case_dir = REGRESSION_DATASET_DIR / "notion_b2b_saas"
    client = RegressionCassetteClient.load(case_dir / "cassette.json")

    outcome = run_brief(
        company="Linear",  # different from the recorded "Notion" → user_msg changes
        market="B2B SaaS knowledge management",
        settings=tmp_settings,
        client=client,
        embedder=stub_embedder,
        fetch_page=lambda url: None,
    )
    # run_brief swallows the exception and records run.status="failed". Confirm
    # the cause was the stale-cassette signal, not a logic bug.
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert "cassette" in outcome.error.lower()
    # And the exception type is what we expect, when invoked directly:
    with pytest.raises(RegressionStaleCassetteError):
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="totally-novel-prompt-text",
            messages=[{"role": "user", "content": "novel input"}],
            tools=[{"name": "emit_x", "description": "x", "input_schema": {}}],
            tool_choice={"type": "tool", "name": "emit_x"},
        )
