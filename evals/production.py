"""Production-side eval ops: sample stream (chunk 7) + drift detection (chunk 8).

Two responsibilities live here because they share the same domain — "what's
happening to runs after they leave the lab?" — and the same data source
(`memory.episodic.EpisodicMemory`). Splitting them into two files would have
been shallower, not cleaner.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory import EpisodicMemory


def maybe_sample_for_review(
    memory: EpisodicMemory,
    run_id: str,
    *,
    rate: float = 0.10,
    rng: random.Random | Callable[[], float] | None = None,
) -> int | None:
    """Roll a die. With probability `rate`, flag the given run for human review
    and return the new review id. Otherwise return None.

    `rng` accepts a `random.Random` instance or a zero-arg callable returning a
    float in [0, 1). Tests pass `lambda: 0.0` (always sample) or
    `lambda: 0.99` (never) to drive deterministic behavior.
    """
    if rate <= 0:
        return None
    if rate >= 1:
        draw = 0.0
    else:
        if rng is None:
            draw = random.random()
        elif isinstance(rng, random.Random):
            draw = rng.random()
        else:
            draw = float(rng())
    if draw >= rate:
        return None
    return memory.start_human_review(run_id=run_id)


# ---------------------------------------------------------------------------
# Drift detection (chunk 8)
# ---------------------------------------------------------------------------


DEFAULT_DRIFT_THRESHOLD = -0.10  # 10-point pass-rate drop


@dataclass
class DriftWindow:
    """Per-skill 7-day rolling pass-rate vs prior 7-day window."""

    skill_name: str
    current_pass_rate: float  # last 7 days
    current_n: int
    prior_pass_rate: float  # prior 7 days
    prior_n: int
    delta: float  # current - prior
    drift_detected: bool


def compute_drift_windows(
    db_path: Path,
    *,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
    now: datetime | None = None,
    min_samples: int = 5,
) -> list[DriftWindow]:
    """For each skill, compute the last-7d vs prior-7d pass-rate delta.

    `drift_detected` fires when delta is at or below `threshold` AND both
    windows have ≥`min_samples` invocations (small-N noise wouldn't generate
    a useful alert).
    """
    now = now or datetime.now(UTC)
    current_start = (now - timedelta(days=7)).isoformat()
    prior_start = (now - timedelta(days=14)).isoformat()

    out: list[DriftWindow] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Two grouped aggregates, one per window, joined by skill.
        rows = conn.execute(
            """
            WITH current AS (
              SELECT skill_name,
                     COUNT(*) AS total,
                     SUM(CASE WHEN eval_passed = 1 THEN 1 ELSE 0 END) AS passed
              FROM skill_invocations
              WHERE started_at >= ?
              GROUP BY skill_name
            ),
            prior AS (
              SELECT skill_name,
                     COUNT(*) AS total,
                     SUM(CASE WHEN eval_passed = 1 THEN 1 ELSE 0 END) AS passed
              FROM skill_invocations
              WHERE started_at >= ? AND started_at < ?
              GROUP BY skill_name
            )
            SELECT c.skill_name,
                   c.total AS current_n,
                   c.passed AS current_passed,
                   COALESCE(p.total, 0) AS prior_n,
                   COALESCE(p.passed, 0) AS prior_passed
            FROM current c
            LEFT JOIN prior p ON p.skill_name = c.skill_name
            ORDER BY c.skill_name ASC
            """,
            (current_start, prior_start, current_start),
        ).fetchall()

    for r in rows:
        cur_n = r["current_n"]
        pri_n = r["prior_n"]
        cur_rate = r["current_passed"] / cur_n if cur_n else 0.0
        pri_rate = r["prior_passed"] / pri_n if pri_n else 0.0
        delta = cur_rate - pri_rate
        drift = cur_n >= min_samples and pri_n >= min_samples and delta <= threshold
        out.append(
            DriftWindow(
                skill_name=r["skill_name"],
                current_pass_rate=cur_rate,
                current_n=cur_n,
                prior_pass_rate=pri_rate,
                prior_n=pri_n,
                delta=delta,
                drift_detected=drift,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Judge-vs-human divergence (chunk 8)
# ---------------------------------------------------------------------------


@dataclass
class JudgeDivergence:
    """Across reviewed runs, count how often the judges and the human
    disagreed on pass/fail. The dashboard shows this so we can flag judges
    whose rubrics need recalibration."""

    total_reviewed: int
    judge_pass_human_fail: int  # judges said pass, human gave ≤2
    judge_fail_human_pass: int  # judges said fail, human gave ≥4
    divergence_rate: float  # disagreements / total


def compute_judge_human_divergence(
    db_path: Path,
    *,
    now: datetime | None = None,
    window_days: int = 7,
    human_pass_threshold: int = 3,
) -> JudgeDivergence:
    """Compare run-level judge consensus (all judges passed?) vs human rating
    (>= threshold = pass) for reviewed samples in the last `window_days`.
    """
    now = now or datetime.now(UTC)
    window_start = (now - timedelta(days=window_days)).isoformat()

    judge_pass_human_fail = 0
    judge_fail_human_pass = 0
    total = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # For each reviewed human_review in the window, look up the run's
        # skill invocations to determine consensus.
        reviews = conn.execute(
            "SELECT run_id, reviewer_rating_overall FROM human_reviews "
            "WHERE reviewed_at >= ? AND reviewer_rating_overall IS NOT NULL",
            (window_start,),
        ).fetchall()
        for review in reviews:
            invocations = conn.execute(
                "SELECT eval_passed FROM skill_invocations WHERE run_id = ?",
                (review["run_id"],),
            ).fetchall()
            if not invocations:
                continue
            total += 1
            judge_passed = all(i["eval_passed"] == 1 for i in invocations)
            human_passed = review["reviewer_rating_overall"] >= human_pass_threshold
            if judge_passed and not human_passed:
                judge_pass_human_fail += 1
            elif not judge_passed and human_passed:
                judge_fail_human_pass += 1
    div_rate = ((judge_pass_human_fail + judge_fail_human_pass) / total) if total else 0.0
    return JudgeDivergence(
        total_reviewed=total,
        judge_pass_human_fail=judge_pass_human_fail,
        judge_fail_human_pass=judge_fail_human_pass,
        divergence_rate=div_rate,
    )


# ---------------------------------------------------------------------------
# Optional Slack alerting
# ---------------------------------------------------------------------------


def post_drift_alert_to_slack(
    windows: list[DriftWindow],
    *,
    webhook_url: str | None = None,
    _httpx_module=None,
) -> bool:
    """If any window flags drift, POST a Slack-formatted message to the webhook.

    No-op when `webhook_url` is empty/None (the typical case — most environments
    don't have one set). Returns True only if a message was actually sent.

    `_httpx_module` exists for the test suite: pass a stub to avoid real HTTP.
    """
    drifting = [w for w in windows if w.drift_detected]
    if not drifting:
        return False
    if not webhook_url:
        return False
    import httpx as _httpx_default

    httpx_mod = _httpx_module or _httpx_default
    lines = [
        f"*Regression drift detected* — {len(drifting)} skill(s) below baseline",
        "",
    ]
    for w in drifting:
        lines.append(
            f"• `{w.skill_name}`: {w.current_pass_rate:.0%} (last 7d, n={w.current_n}) "
            f"vs {w.prior_pass_rate:.0%} (prior 7d, n={w.prior_n}) "
            f"— Δ {w.delta:+.0%}"
        )
    httpx_mod.post(webhook_url, json={"text": "\n".join(lines)}, timeout=10.0)
    return True


# Re-export for cleaner imports.
Callable_ = Callable  # type: ignore[assignment]
