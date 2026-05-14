"""meta/run.py — the meta-agent entry point (dry-run + PR-opening paths)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from guardrails import RunBudget
from memory import EpisodicMemory, SkillInvocationRecord
from meta.github_pr import OpenedPR
from meta.run import run_meta_agent

_NOW = datetime(2026, 5, 14, tzinfo=UTC)


class _FakePublisher:
    """Records the publish call instead of touching git/GitHub."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def publish(self, *, branch: str, title: str, body: str, diff: str) -> OpenedPR:
        self.calls.append({"branch": branch, "title": title, "body": body, "diff": diff})
        return OpenedPR(number=42, url="https://github.com/x/y/pull/42", branch=branch)


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


def test_run_meta_agent_non_dry_run_requires_a_publisher(tmp_path: Path, fake_client):
    """Non-dry-run with no publisher must fail loudly, not silently no-op."""
    db_path = _seed_drift(tmp_path)
    fake_client.load_cassette("meta_proposal")
    budget = RunBudget(max_cost_usd=5.0)
    with pytest.raises(ValueError, match="publisher"):
        run_meta_agent(db_path, client=fake_client, budget=budget, dry_run=False, now=_NOW)


def test_run_meta_agent_non_dry_run_opens_pr_and_records_proposal(tmp_path: Path, fake_client):
    db_path = _seed_drift(tmp_path)
    fake_client.load_cassette("meta_proposal")
    budget = RunBudget(max_cost_usd=5.0)
    publisher = _FakePublisher()
    memory = EpisodicMemory(db_path)

    url = run_meta_agent(
        db_path,
        client=fake_client,
        budget=budget,
        dry_run=False,
        now=_NOW,
        publisher=publisher,
        memory=memory,
    )

    assert url == "https://github.com/x/y/pull/42"
    assert len(publisher.calls) == 1
    assert publisher.calls[0]["branch"] == "meta-agent/drift-score-queries-20260514"
    assert "Reviewer checklist" in publisher.calls[0]["body"]

    rows = (
        sqlite3.connect(db_path)
        .execute("SELECT target_pattern, pr_number, branch, status FROM meta_proposals")
        .fetchall()
    )
    assert rows == [
        ("drift:score_queries", 42, "meta-agent/drift-score-queries-20260514", "proposed")
    ]
