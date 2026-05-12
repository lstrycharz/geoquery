"""Regression suite — replays recorded cassettes deterministically and
asserts the resulting eval-outcome profile matches the recorded baseline.

Cases live under `regression_dataset/<slug>/` with three files:
- `input.json`       — {company, market, sitemap_url?}
- `cassette.json`    — sha256(sys+usr+model) → CassetteEntry
- `expected.json`    — {tier, eval_profile, status, source, notes}

Two tiers, picked up automatically from `expected.json::tier`:
- `regression_smoke` — pre-commit gate (~5 cases, <10s)
- `regression_full`  — PR-CI gate (smoke + full, ~30 cases, <30s)

Re-record a case with `pytest -m regression_record` after an intentional
prompt change. Adding a directory under regression_dataset/ with a tier
field in expected.json picks it up here automatically.
"""

from __future__ import annotations

import json

import pytest

from agent import run_brief
from evals.regression import REGRESSION_DATASET_DIR, RegressionCassetteClient
from memory import EpisodicMemory


def _discover_cases(tier: str | None = None) -> list[str]:
    """Walk regression_dataset/ and return slugs whose expected.json matches the
    given tier. If `tier` is None, returns every case."""
    if not REGRESSION_DATASET_DIR.is_dir():
        return []
    cases: list[str] = []
    for child in sorted(REGRESSION_DATASET_DIR.iterdir()):
        if not child.is_dir():
            continue
        if not all((child / f).is_file() for f in ("input.json", "cassette.json", "expected.json")):
            continue
        if tier is None:
            cases.append(child.name)
            continue
        case_tier = json.loads((child / "expected.json").read_text()).get("tier", "smoke")
        if case_tier == tier:
            cases.append(child.name)
    return cases


def _replay_case(slug: str, tmp_settings, stub_embedder) -> None:
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


# ---------------------------------------------------------------------------
# Smoke tier — runs in pre-commit. `pytest -m regression_smoke`.
# ---------------------------------------------------------------------------


@pytest.mark.regression_smoke
@pytest.mark.parametrize("slug", _discover_cases(tier="smoke"))
def test_regression_smoke(slug: str, tmp_settings, stub_embedder) -> None:
    _replay_case(slug, tmp_settings, stub_embedder)


# ---------------------------------------------------------------------------
# Full tier — runs in PR CI together with smoke. `pytest -m regression_full`.
# ---------------------------------------------------------------------------


@pytest.mark.regression_full
@pytest.mark.parametrize("slug", _discover_cases(tier="full"))
def test_regression_full(slug: str, tmp_settings, stub_embedder) -> None:
    _replay_case(slug, tmp_settings, stub_embedder)


# ---------------------------------------------------------------------------
# Sanity / harness self-checks (these run in the default pytest pass).
# ---------------------------------------------------------------------------


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


def test_smoke_tier_has_expected_size():
    """Plan target: 5 smoke cases for pre-commit (~10s budget)."""
    smoke = _discover_cases(tier="smoke")
    assert len(smoke) == 5, f"smoke tier should have 5 cases, has {len(smoke)}: {smoke}"


def test_full_tier_brings_total_to_30_plus():
    smoke = _discover_cases(tier="smoke")
    full = _discover_cases(tier="full")
    assert len(smoke) + len(full) >= 30, (
        f"plan targets 30+ cases; have {len(smoke)} smoke + {len(full)} full"
    )


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
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert "cassette" in outcome.error.lower()
    with pytest.raises(RegressionStaleCassetteError):
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="totally-novel-prompt-text",
            messages=[{"role": "user", "content": "novel input"}],
            tools=[{"name": "emit_x", "description": "x", "input_schema": {}}],
            tool_choice={"type": "tool", "name": "emit_x"},
        )


def test_replay_each_slug_has_unique_cassette_hash_set():
    """Bootstraps share fake LLM responses but DIFFERENT Company/Market → each
    cassette should have a unique set of hash keys. If two slugs ever share the
    exact same hash set, somebody copy-pasted instead of recording."""
    cases = _discover_cases()
    hash_sets: dict[str, frozenset[str]] = {}
    for slug in cases:
        cassette_path = REGRESSION_DATASET_DIR / slug / "cassette.json"
        keys = frozenset(json.loads(cassette_path.read_text()).keys())
        hash_sets[slug] = keys
    # Build a reverse map: hashset → slugs that share it.
    reverse: dict[frozenset[str], list[str]] = {}
    for slug, hs in hash_sets.items():
        reverse.setdefault(hs, []).append(slug)
    duplicates = {hs: slugs for hs, slugs in reverse.items() if len(slugs) > 1}
    assert not duplicates, f"slugs share an identical cassette hash set: {duplicates}"
