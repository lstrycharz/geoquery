"""Episodic memory — schema init, run start/finish, skill_invocations log."""

from __future__ import annotations

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
