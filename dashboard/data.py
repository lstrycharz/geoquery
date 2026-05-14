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


def brief_quality_trend_by_run(db_path: Path) -> dict[str, Any]:
    """The learning curve (v3 chunk 10): per completed run, a 0-1 quality score
    plotted against run sequence, plus the merged meta-agent PRs positioned on
    the same axis.

    `quality` is the mean of whichever signals exist for the run:
      - judge score: the run's eval composite (clean invocation fraction);
      - outcome score: `confidence` if the prediction was top-10, else its
        complement — present only for runs the outcome judge scored;
      - human score: the reviewer's 1-5 rating mapped to 0-1 — present only
        for runs that were sampled and reviewed.

    All three live in episodic.db, so the dashboard never touches semantic.db.
    """
    with _connect(db_path) as conn:
        runs = conn.execute(
            "SELECT id, company, started_at FROM runs "
            "WHERE status = 'completed' ORDER BY started_at ASC, id ASC"
        ).fetchall()
        judge_rows = conn.execute(
            "SELECT run_id, COUNT(*) AS evaluated, "
            "SUM(CASE WHEN eval_passed = 1 "
            "         AND (eval_details_json IS NULL OR eval_details_json = '[]') "
            "    THEN 1 ELSE 0 END) AS clean "
            "FROM skill_invocations WHERE eval_passed IS NOT NULL GROUP BY run_id"
        ).fetchall()
        outcome_rows = conn.execute(
            "SELECT run_id, predicted_top10, confidence FROM outcome_predictions "
            "ORDER BY created_at ASC, id ASC"
        ).fetchall()
        human_rows = conn.execute(
            "SELECT run_id, reviewer_rating_overall FROM human_reviews "
            "WHERE reviewer_rating_overall IS NOT NULL ORDER BY reviewed_at ASC, id ASC"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT pr_number, target_pattern, merged_at, status FROM meta_proposals "
            "WHERE merged_at IS NOT NULL ORDER BY merged_at ASC"
        ).fetchall()

    # judge composite per run — 1.0 (neutral) when nothing was evaluated, to
    # match EpisodicMemory.compute_run_eval_score.
    judge = {
        r["run_id"]: (r["clean"] / r["evaluated"] if r["evaluated"] else 1.0) for r in judge_rows
    }
    # Later predictions/reviews overwrite earlier ones — we want the latest.
    outcome = {
        r["run_id"]: (r["confidence"] if r["predicted_top10"] else 1.0 - r["confidence"])
        for r in outcome_rows
    }
    human = {r["run_id"]: (r["reviewer_rating_overall"] - 1) / 4 for r in human_rows}

    points: list[dict[str, Any]] = []
    for seq, run in enumerate(runs, start=1):
        rid = run["id"]
        judge_score = judge.get(rid, 1.0)
        outcome_score = outcome.get(rid)
        human_score = human.get(rid)
        signals = [judge_score]
        if outcome_score is not None:
            signals.append(outcome_score)
        if human_score is not None:
            signals.append(human_score)
        points.append(
            {
                "run_seq": seq,
                "run_id": rid,
                "company": run["company"],
                "started_at": run["started_at"],
                "judge_score": judge_score,
                "outcome_score": outcome_score,
                "human_score": human_score,
                "quality": sum(signals) / len(signals),
            }
        )

    # Position each merged meta-PR at the run-sequence count up to its merge:
    # the number of runs that had already started when the change landed.
    markers: list[dict[str, Any]] = []
    for m in meta_rows:
        run_seq = sum(1 for run in runs if run["started_at"] <= m["merged_at"])
        markers.append(
            {
                "run_seq": run_seq,
                "pr_number": m["pr_number"],
                "target_pattern": m["target_pattern"],
                "merged_at": m["merged_at"],
                "status": m["status"],
            }
        )

    return {"points": points, "meta_pr_markers": markers}


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
