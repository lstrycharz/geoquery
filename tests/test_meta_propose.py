"""meta/propose.py — the meta-agent's single LLM call.

The anti-Goodhart property under test: the context handed to the model never
contains the rubric prose of the judges it is optimizing against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.rubric_loader import RUBRICS_DIR
from guardrails import RunBudget
from memory import EpisodicMemory, SkillInvocationRecord
from meta.analyze import Pattern
from meta.edit_surface import EditSurfaceViolation
from meta.propose import Proposal, _build_context, propose

_DRIFT_PATTERN = Pattern(
    kind="drift",
    signal_id="drift:score_queries",
    summary="score_queries pass-rate dropped 100% → 33% over the last 7 days",
    severity=0.67,
    evidence={"skill_name": "score_queries", "current_pass_rate": 0.33},
)


def _seed_outputs(tmp_path: Path) -> Path:
    mem = EpisodicMemory(tmp_path / "episodic.db")
    run = mem.start_run(company="Acme", market="project management")
    for i in range(3):
        mem.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name="score_queries",
                attempt=1,
                model="claude-sonnet-4-6",
                input_json="{}",
                output_json=f'{{"composite": 5.0, "rationale": "sample output {i}"}}',
                eval_passed=False,
                started_at="2026-05-11T00:00:00+00:00",
            )
        )
    return mem.db_path


def test_build_context_excludes_rubric_prose(tmp_path: Path):
    """propose() must never see the grader's text — only the pattern and the
    actual skill outputs. If it could read the rubric it would optimize
    against the rubric instead of the work."""
    db_path = _seed_outputs(tmp_path)
    context = _build_context(_DRIFT_PATTERN, db_path)

    for rubric_file in RUBRICS_DIR.glob("*.md"):
        rubric_text = rubric_file.read_text(encoding="utf-8")
        assert rubric_text not in context, f"rubric prose leaked: {rubric_file.name}"


def test_build_context_includes_sample_skill_outputs(tmp_path: Path):
    """The context has to be useful — it carries the affected skill's actual
    recent outputs so the model improves the real work."""
    db_path = _seed_outputs(tmp_path)
    context = _build_context(_DRIFT_PATTERN, db_path)
    assert "score_queries" in context
    assert "sample output" in context


def test_propose_returns_proposal_from_llm(tmp_path: Path, fake_client):
    db_path = _seed_outputs(tmp_path)
    fake_client.load_cassette("meta_proposal")
    budget = RunBudget(max_cost_usd=5.0)

    proposal = propose(_DRIFT_PATTERN, client=fake_client, budget=budget, db_path=db_path)

    assert isinstance(proposal, Proposal)
    assert proposal.target_pattern == "drift:score_queries"
    assert proposal.hypothesis
    assert proposal.edit_paths
    # Every path the LLM proposed is inside the edit surface.
    for path in proposal.edit_paths:
        assert path.startswith(("skills/prompts/", "evals/rubrics/", "evals/proposed/"))


def test_propose_rejects_out_of_surface_edit_paths(tmp_path: Path, fake_client):
    """If the model proposes a path outside the edit surface, propose() aborts
    loudly — we don't open a doomed PR."""
    db_path = _seed_outputs(tmp_path)
    fake_client.set_cassette(
        "meta_proposal",
        {
            "input": {
                "change_type": "prompt",
                "hypothesis": "loosen the grader",
                "diff": "--- a/memory/schema.sql\n+++ b/memory/schema.sql\n",
                "predicted_effect": "scores go up",
                "edit_paths": ["memory/schema.sql"],
            }
        },
    )
    budget = RunBudget(max_cost_usd=5.0)
    with pytest.raises(EditSurfaceViolation):
        propose(_DRIFT_PATTERN, client=fake_client, budget=budget, db_path=db_path)
