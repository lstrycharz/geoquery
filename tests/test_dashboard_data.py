"""dashboard/data.py — pure functions over data/episodic.db.

No Streamlit imports here. Pages import these helpers and render; the helpers
own SQL, the pages own presentation. Lets us unit-test the query logic without
a browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.data import (
    cost_per_run,
    pass_rate_per_skill_per_day,
    recent_runs,
    skill_failure_rate,
)
from memory import EpisodicMemory, SkillInvocationRecord


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "episodic.db"
    memory = EpisodicMemory(db_path)
    # Seed 3 runs with mixed status + cost so the helper has something to read.
    for company, market, status, cost in [
        ("Notion", "B2B SaaS knowledge mgmt", "completed", 0.42),
        ("Linear", "B2B SaaS project mgmt", "completed", 0.51),
        ("Glossier", "DTC beauty", "failed", 0.18),
    ]:
        run = memory.start_run(company=company, market=market)
        memory.finish_run(
            run_id=run.id,
            status=status,
            total_cost_usd=cost,
            brief_path=f"briefs/{run.id}_{company.lower()}.md",
        )
        # Add a skill invocation per run so we can test cross-table reads later.
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name="research_company",
                attempt=1,
                model="claude-sonnet-4-6",
                input_json="{}",
                started_at=run.started_at,
                eval_passed=True,
                cost_usd=cost / 2,
            )
        )
    return db_path


def test_recent_runs_returns_all_seeded_runs(populated_db):
    rows = recent_runs(populated_db, limit=10)
    assert len(rows) == 3
    companies = {r["company"] for r in rows}
    assert companies == {"Notion", "Linear", "Glossier"}


def test_recent_runs_sorted_descending_by_started_at(populated_db):
    rows = recent_runs(populated_db, limit=10)
    timestamps = [r["started_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_recent_runs_respects_limit(populated_db):
    rows = recent_runs(populated_db, limit=2)
    assert len(rows) == 2


def test_recent_runs_returns_empty_when_no_data(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    EpisodicMemory(db_path)  # creates schema, no rows
    assert recent_runs(db_path, limit=10) == []


def test_pass_rate_per_skill_per_day_groups_correctly(tmp_path: Path):
    """Two skill invocations, same skill, same day, one pass + one fail → 50%."""
    db_path = tmp_path / "episodic.db"
    memory = EpisodicMemory(db_path)
    run = memory.start_run(company="X", market="Y")
    memory.finish_run(run_id=run.id, status="completed", total_cost_usd=0.1, brief_path=None)
    for passed, attempt in [(True, 1), (False, 2)]:
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name="define_icp",
                attempt=attempt,
                model="claude-sonnet-4-6",
                input_json="{}",
                started_at=run.started_at,
                eval_passed=passed,
            )
        )
    rows = pass_rate_per_skill_per_day(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["skill_name"] == "define_icp"
    assert row["total"] == 2
    assert row["passed"] == 1
    assert row["pass_rate"] == 0.5


def test_cost_per_run_returns_completed_runs_only(populated_db):
    rows = cost_per_run(populated_db)
    # populated_db seeds 3 runs, 2 completed and 1 failed; only completed costs return.
    assert len(rows) == 2
    costs = sorted(r["total_cost_usd"] for r in rows)
    assert costs == [0.42, 0.51]


def test_skill_failure_rate_counts_eval_passed_zero_and_null(tmp_path: Path):
    """A skill that flipped to eval_passed=False once and eval_passed=None once
    out of 4 total invocations should show 50% failure rate."""
    db_path = tmp_path / "episodic.db"
    memory = EpisodicMemory(db_path)
    run = memory.start_run(company="X", market="Y")
    memory.finish_run(run_id=run.id, status="completed", total_cost_usd=0.1, brief_path=None)
    for passed, attempt in [(True, 1), (True, 2), (False, 3), (None, 4)]:
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name="analyze_serp",
                attempt=attempt,
                model="claude-sonnet-4-6",
                input_json="{}",
                started_at=run.started_at,
                eval_passed=passed,
            )
        )
    rows = skill_failure_rate(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["skill_name"] == "analyze_serp"
    assert row["total"] == 4
    assert row["failures"] == 2  # one False + one NULL
    assert row["failure_rate"] == 0.5


def test_recent_runs_uses_parameterized_sql(populated_db):
    """Defense-in-depth: source code of the helper must use `?` placeholders,
    not f-strings, for any user-supplied value. Plain text check — brittle if
    we ever extract the SQL into a constant, but cheap insurance against a
    refactor that accidentally interpolates `limit` into the SQL string.
    """
    from dashboard import data as data_module

    src = Path(data_module.__file__).read_text(encoding="utf-8")
    assert "LIMIT ?" in src
    assert "LIMIT {" not in src
    assert "f'" not in src.split("def recent_runs")[1]


# ---------------------------------------------------------------------------
# v3 chunk 10 — brief_quality_trend_by_run (learning curve)
# ---------------------------------------------------------------------------


def _completed_run(memory, *, company, started_at, clean_invocations, failed_invocations=0):
    run = memory.start_run(company=company, market="m")
    with memory._connect() as conn:
        conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", (started_at, run.id))
    for i in range(clean_invocations):
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=f"skill_{i}",
                attempt=1,
                model="claude-sonnet-4-6",
                input_json="{}",
                started_at=started_at,
                eval_passed=True,
            )
        )
    for i in range(failed_invocations):
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=f"skill_f{i}",
                attempt=1,
                model="claude-sonnet-4-6",
                input_json="{}",
                started_at=started_at,
                eval_passed=False,
                eval_details_json='["fail"]',
            )
        )
    memory.finish_run(run.id, "completed", 1.0, "/b.md")
    return run.id


def test_brief_quality_trend_orders_by_run_sequence(tmp_path: Path):
    from dashboard.data import brief_quality_trend_by_run

    db = tmp_path / "episodic.db"
    mem = EpisodicMemory(db)
    _completed_run(
        mem, company="First", started_at="2026-05-01T00:00:00+00:00", clean_invocations=2
    )
    _completed_run(
        mem, company="Second", started_at="2026-05-03T00:00:00+00:00", clean_invocations=2
    )

    trend = brief_quality_trend_by_run(db)
    seqs = [p["run_seq"] for p in trend["points"]]
    companies = [p["company"] for p in trend["points"]]
    assert seqs == [1, 2]
    assert companies == ["First", "Second"]


def test_brief_quality_trend_quality_is_judge_score_without_other_signals(tmp_path: Path):
    from dashboard.data import brief_quality_trend_by_run

    db = tmp_path / "episodic.db"
    mem = EpisodicMemory(db)
    # 1 clean + 1 failed invocation -> judge score 0.5, no outcome/human signal.
    _completed_run(
        mem,
        company="X",
        started_at="2026-05-01T00:00:00+00:00",
        clean_invocations=1,
        failed_invocations=1,
    )
    point = brief_quality_trend_by_run(db)["points"][0]
    assert point["judge_score"] == 0.5
    assert point["outcome_score"] is None
    assert point["human_score"] is None
    assert point["quality"] == 0.5


def test_brief_quality_trend_blends_judge_outcome_and_human(tmp_path: Path):
    from dashboard.data import brief_quality_trend_by_run

    db = tmp_path / "episodic.db"
    mem = EpisodicMemory(db)
    run_id = _completed_run(
        mem,
        company="X",
        started_at="2026-05-01T00:00:00+00:00",
        clean_invocations=2,
    )  # judge score 1.0
    mem.record_outcome_prediction(
        run_id=run_id,
        predicted_top10=True,
        confidence=0.6,
        reasoning="r",
        model="claude-opus-4-7",
    )  # outcome score 0.6
    review_id = mem.start_human_review(run_id=run_id)
    mem.record_human_review(review_id=review_id, rating_overall=5)  # human score (5-1)/4 = 1.0

    point = brief_quality_trend_by_run(db)["points"][0]
    assert point["judge_score"] == 1.0
    assert point["outcome_score"] == 0.6
    assert point["human_score"] == 1.0
    assert point["quality"] == pytest.approx((1.0 + 0.6 + 1.0) / 3)


def test_brief_quality_trend_positions_meta_pr_markers(tmp_path: Path):
    from dashboard.data import brief_quality_trend_by_run

    db = tmp_path / "episodic.db"
    mem = EpisodicMemory(db)
    _completed_run(mem, company="A", started_at="2026-05-01T00:00:00+00:00", clean_invocations=1)
    _completed_run(mem, company="B", started_at="2026-05-05T00:00:00+00:00", clean_invocations=1)
    pid = mem.record_meta_proposal(
        target_pattern="drift:score_queries",
        change_type="prompt",
        hypothesis="h",
        pr_number=7,
    )
    mem.update_meta_proposal(pid, status="measured", merged_at="2026-05-03T00:00:00+00:00")

    markers = brief_quality_trend_by_run(db)["meta_pr_markers"]
    assert len(markers) == 1
    # one run started before the merge → marker sits at run_seq 1
    assert markers[0]["run_seq"] == 1
    assert markers[0]["pr_number"] == 7
    assert markers[0]["status"] == "measured"


def test_brief_quality_trend_empty_db(tmp_path: Path):
    from dashboard.data import brief_quality_trend_by_run

    db = tmp_path / "episodic.db"
    EpisodicMemory(db)
    trend = brief_quality_trend_by_run(db)
    assert trend == {"points": [], "meta_pr_markers": []}
