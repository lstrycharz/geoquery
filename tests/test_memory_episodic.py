"""Episodic memory — schema init, run start/finish, skill_invocations log."""

from __future__ import annotations

import pytest

from memory import EpisodicMemory, SkillInvocationRecord
from memory.episodic import _now


def test_start_run_creates_row(tmp_path):
    db = tmp_path / "ep.db"
    mem = EpisodicMemory(db_path=db)
    run = mem.start_run(company="Notion", market="B2B SaaS")
    assert run.id
    assert run.status == "in_progress"
    fetched = mem.get_run(run.id)
    assert fetched["company"] == "Notion"
    assert fetched["market"] == "B2B SaaS"
    assert fetched["status"] == "in_progress"


def test_finish_run_updates_status_and_cost(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run(company="X", market="Y")
    mem.finish_run(run.id, "completed", 0.123, "/briefs/x.md")
    fetched = mem.get_run(run.id)
    assert fetched["status"] == "completed"
    assert fetched["total_cost_usd"] == 0.123
    assert fetched["brief_path"] == "/briefs/x.md"


def test_log_skill_invocation_persists(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run(company="X", market="Y")
    mem.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run.id,
            skill_name="define_icp",
            attempt=1,
            model="claude-sonnet-4-6",
            input_json='{"company":"X","market":"Y"}',
            output_json='{"segments":[]}',
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.012,
            duration_ms=4200,
            started_at=_now(),
        )
    )
    rows = mem.get_invocations(run.id)
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "define_icp"
    assert rows[0]["attempt"] == 1
    assert rows[0]["cost_usd"] == 0.012


def test_list_runs_orders_newest_first(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    a = mem.start_run("a", "m")
    b = mem.start_run("b", "m")
    rows = mem.list_runs()
    assert rows[0]["id"] == b.id
    assert rows[1]["id"] == a.id


# ---------------------------------------------------------------------------
# v3 chunk 5 — winning patterns
# ---------------------------------------------------------------------------


def test_record_and_get_latest_winning_patterns(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    mem.record_winning_patterns(
        briefs_analyzed=10,
        min_eval_score=0.82,
        patterns=["names a specific persona pain", "5-6 sections each with an action"],
    )
    latest = mem.get_latest_winning_patterns()
    assert latest is not None
    assert latest["briefs_analyzed"] == 10
    assert latest["patterns"] == [
        "names a specific persona pain",
        "5-6 sections each with an action",
    ]


def test_get_latest_winning_patterns_returns_most_recent(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    mem.record_winning_patterns(
        briefs_analyzed=5,
        min_eval_score=0.5,
        patterns=["old"],
        extracted_at="2026-01-01T00:00:00+00:00",
    )
    mem.record_winning_patterns(
        briefs_analyzed=8,
        min_eval_score=0.7,
        patterns=["new"],
        extracted_at="2026-05-01T00:00:00+00:00",
    )
    assert mem.get_latest_winning_patterns()["patterns"] == ["new"]


def test_get_latest_winning_patterns_none_when_empty(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    assert mem.get_latest_winning_patterns() is None


# ---------------------------------------------------------------------------
# v3 chunk 6 — escalations
# ---------------------------------------------------------------------------


def test_record_and_get_escalations(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run("Acme", "project management")
    mem.record_escalation(
        run_id=run.id,
        skill_name="score_queries",
        attempt_failures=[["[a] fail one"], ["[a] fail two"], ["[a] fail three"]],
        final_output_json='{"composite": 5.0}',
    )
    rows = mem.get_escalations(run.id)
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "score_queries"
    assert rows[0]["attempt_failures"] == [
        ["[a] fail one"],
        ["[a] fail two"],
        ["[a] fail three"],
    ]
    assert rows[0]["final_output_json"] == '{"composite": 5.0}'


def test_get_escalations_empty_when_none_recorded(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run("Acme", "m")
    assert mem.get_escalations(run.id) == []


# ---------------------------------------------------------------------------
# v3 chunk 7 — outcome predictions
# ---------------------------------------------------------------------------


def test_record_and_get_outcome_prediction(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run("Acme", "project management")
    mem.record_outcome_prediction(
        run_id=run.id,
        predicted_top10=True,
        confidence=0.72,
        reasoning="specific angle, strong intent match",
        model="claude-opus-4-7",
    )
    pred = mem.get_outcome_prediction(run.id)
    assert pred is not None
    assert pred["predicted_top10"] is True
    assert pred["confidence"] == 0.72
    assert pred["model"] == "claude-opus-4-7"


def test_get_outcome_prediction_none_when_absent(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    run = mem.start_run("Acme", "m")
    assert mem.get_outcome_prediction(run.id) is None


def _completed_run_with_brief(mem, company):
    run = mem.start_run(company, "project management")
    mem.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run.id,
            skill_name="draft_content_brief",
            attempt=1,
            model="claude-sonnet-4-6",
            input_json="{}",
            output_json='{"angle": "x"}',
            started_at=_now(),
        )
    )
    mem.finish_run(run.id, "completed", 1.0, "/briefs/x.md")
    return run


def test_runs_pending_outcome_prediction_selects_unscored_completed_runs(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "ep.db")
    pending = _completed_run_with_brief(mem, "Pending")
    sampled = _completed_run_with_brief(mem, "Sampled")
    mem.start_human_review(run_id=sampled.id)
    already = _completed_run_with_brief(mem, "Already")
    mem.record_outcome_prediction(
        run_id=already.id,
        predicted_top10=False,
        confidence=0.3,
        reasoning="r",
        model="claude-opus-4-7",
    )
    # An in-progress run with no brief — must be excluded.
    mem.start_run("InProgress", "m")

    rows = mem.runs_pending_outcome_prediction()
    by_id = {r["id"]: r for r in rows}

    assert set(by_id) == {pending.id, sampled.id}
    assert by_id[pending.id]["sampled"] is False
    assert by_id[sampled.id]["sampled"] is True


# ---------------------------------------------------------------------------
# v3 chunk 8 — outcome feedback blend
# ---------------------------------------------------------------------------


def test_blend_eval_score_unchanged_without_a_prediction():
    from memory.episodic import blend_eval_score

    assert blend_eval_score(0.7) == 0.7


def test_blend_eval_score_top10_prediction_pulls_score_up():
    from memory.episodic import blend_eval_score

    # judge 0.5, prediction top-10 @ 0.9 confidence -> 0.6*0.5 + 0.4*0.9 = 0.66
    blended = blend_eval_score(0.5, predicted_top10=True, confidence=0.9)
    assert blended == pytest.approx(0.66)


def test_blend_eval_score_negative_prediction_pulls_score_down():
    from memory.episodic import blend_eval_score

    # judge 0.8, prediction NOT top-10 @ 0.9 confidence -> outcome score 0.1
    # -> 0.6*0.8 + 0.4*0.1 = 0.52
    blended = blend_eval_score(0.8, predicted_top10=False, confidence=0.9)
    assert blended == pytest.approx(0.52)
