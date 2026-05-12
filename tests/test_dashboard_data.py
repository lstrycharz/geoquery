"""dashboard/data.py — pure functions over data/episodic.db.

No Streamlit imports here. Pages import these helpers and render; the helpers
own SQL, the pages own presentation. Lets us unit-test the query logic without
a browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.data import recent_runs
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
