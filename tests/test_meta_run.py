"""meta/run.py — the meta-agent entry point. Chunk 2: --dry-run only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from guardrails import RunBudget
from memory import EpisodicMemory, SkillInvocationRecord
from meta.run import run_meta_agent

_NOW = datetime(2026, 5, 14, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


def _seed_drift(tmp_path: Path) -> Path:
    mem = EpisodicMemory(tmp_path / "episodic.db")
    run = mem.start_run(company="Acme", market="project management")
    # score_queries: 6 recent invocations (2 pass) vs 6 prior (6 pass) → drift.
    for i in range(6):
        for days_ago, passed in ((3, i < 2), (10, True)):
            mem.log_skill_invocation(
                SkillInvocationRecord(
                    run_id=run.id,
                    skill_name="score_queries",
                    attempt=1,
                    model="claude-sonnet-4-6",
                    input_json="{}",
                    output_json='{"composite": 5.0, "rationale": "sample"}',
                    eval_passed=passed,
                    eval_details_json=None if passed else '["fail"]',
                    started_at=_iso(days_ago),
                )
            )
    return mem.db_path


def test_run_meta_agent_emits_proposal_markdown(tmp_path: Path, fake_client):
    db_path = _seed_drift(tmp_path)
    fake_client.load_cassette("meta_proposal")
    budget = RunBudget(max_cost_usd=5.0)

    markdown = run_meta_agent(db_path, client=fake_client, budget=budget, dry_run=True, now=_NOW)

    assert markdown is not None
    assert "drift:score_queries" in markdown
    assert "skills/prompts/score_queries.md" in markdown
    # The hypothesis text from the cassette is carried through.
    assert "banding" in markdown or "band" in markdown


def test_run_meta_agent_returns_none_when_no_patterns(tmp_path: Path, fake_client):
    mem = EpisodicMemory(tmp_path / "episodic.db")  # empty — no drift, no divergence
    budget = RunBudget(max_cost_usd=5.0)
    result = run_meta_agent(mem.db_path, client=fake_client, budget=budget, dry_run=True, now=_NOW)
    assert result is None


def test_run_meta_agent_non_dry_run_not_yet_implemented(tmp_path: Path, fake_client):
    """PR opening lands in chunk 4 — until then non-dry-run must fail loudly,
    not silently no-op."""
    db_path = _seed_drift(tmp_path)
    fake_client.load_cassette("meta_proposal")
    budget = RunBudget(max_cost_usd=5.0)
    with pytest.raises(NotImplementedError):
        run_meta_agent(db_path, client=fake_client, budget=budget, dry_run=False, now=_NOW)
