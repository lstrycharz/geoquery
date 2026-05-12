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
