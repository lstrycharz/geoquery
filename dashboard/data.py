"""Pure data helpers for the Streamlit dashboard.

This module deliberately has no Streamlit imports. Pages call these functions
to fetch dicts/rows and then render them; the helpers own the SQL. Two reasons:
unit-tested boundary, and a clean swap-out if a future page wants pandas / a
chart that needs raw rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def recent_runs(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent `limit` rows from the runs table, newest first.

    Parameterized — `limit` always travels as a query parameter, never spliced
    into the SQL string.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, started_at, ended_at, company, market, status, "
            "total_cost_usd, brief_path "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def pass_rate_per_skill_per_day(db_path: Path) -> list[dict[str, Any]]:
    """For each (skill_name, day), return totals + pass_rate.

    Used by the Evals page to plot per-skill pass-rate trends over time and by
    the Drift page (chunk 8) to compute a 7-day rolling average.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT skill_name, "
            "       substr(started_at, 1, 10) AS day, "
            "       COUNT(*) AS total, "
            "       SUM(CASE WHEN eval_passed = 1 THEN 1 ELSE 0 END) AS passed "
            "FROM skill_invocations "
            "GROUP BY skill_name, day "
            "ORDER BY day ASC, skill_name ASC"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["pass_rate"] = d["passed"] / d["total"] if d["total"] else 0.0
        out.append(d)
    return out


def cost_per_run(db_path: Path) -> list[dict[str, Any]]:
    """Return total_cost_usd per completed run. The Costs page renders this
    as a histogram + p50/p95 summary statistics."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, company, market, total_cost_usd, started_at "
            "FROM runs WHERE status = 'completed' ORDER BY started_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def pending_reviews(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Sampled runs awaiting a human rating. Used by the Review_Queue page."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT hr.id AS review_id, hr.run_id, hr.sampled_at, "
            "       r.company, r.market, r.brief_path, r.total_cost_usd "
            "FROM human_reviews hr "
            "JOIN runs r ON r.id = hr.run_id "
            "WHERE hr.reviewed_at IS NULL "
            "ORDER BY hr.sampled_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def judge_outcomes_for_run(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    """For each skill invocation of a run, return the eval outcome.

    The Review_Queue form renders these so the human can see what the judges
    said at run-time and decide whether their rating diverges from the
    machine verdict.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT skill_name, attempt, model, eval_passed, eval_details_json, "
            "       cost_usd, started_at "
            "FROM skill_invocations WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def skill_failure_rate(db_path: Path) -> list[dict[str, Any]]:
    """For each skill, count failed + null invocations as 'failures'.

    `eval_passed IS NULL` covers two cases that both look like a skill-level
    failure to the user: (a) the skill threw before eval ran; (b) the skill
    predates the v2 eval framework (legacy rows). Either way: we want the
    Tools page to surface them.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT skill_name, "
            "       COUNT(*) AS total, "
            "       SUM(CASE WHEN eval_passed = 0 OR eval_passed IS NULL THEN 1 ELSE 0 END) "
            "         AS failures "
            "FROM skill_invocations "
            "GROUP BY skill_name "
            "ORDER BY skill_name ASC"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["failure_rate"] = d["failures"] / d["total"] if d["total"] else 0.0
        out.append(d)
    return out
