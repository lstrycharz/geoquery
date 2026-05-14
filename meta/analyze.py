"""Rule-based pattern detection for the meta-agent — NO LLM.

`analyze()` reads the episodic DB read-only and returns a deterministic,
severity-ranked list of Patterns. Keeping this rule-based (not an LLM call)
is a reward-hacking defense: the meta-agent can't cherry-pick which pattern
to "discover" — the ranking is fixed by code.

Signal sources (v3 chunk 2): drift windows + judge-human divergence. Later
chunks add escalation clusters + regression dips additively — analyze just
gains signal functions, no refactor of this contract.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from evals.production import compute_drift_windows, compute_judge_human_divergence

# A pattern is "stale" — skip re-proposing it — if a rejected or inconclusive
# proposal already targeted it within this many days.
REJECTED_COOLDOWN_DAYS = 30
_SKIP_STATUSES = ("rejected", "inconclusive")

# A divergence signal needs enough reviewed runs to be worth acting on.
_MIN_REVIEWED_FOR_DIVERGENCE = 5


@dataclass(frozen=True)
class Pattern:
    """One systematic issue worth a meta-agent proposal."""

    kind: str  # "drift" | "divergence"
    signal_id: str  # stable identity for dedup, e.g. "drift:score_queries"
    summary: str  # one-line, human-readable
    severity: float  # 0-1, drives ranking
    evidence: dict[str, Any] = field(default_factory=dict)


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    """Open the episodic DB read-only — the meta-agent must never be able to
    mutate the eval history it analyzes."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _recently_skipped(db_path: Path, now: datetime) -> set[str]:
    """signal_ids of patterns a rejected/inconclusive proposal already targeted
    inside the cooldown window."""
    cutoff = (now - timedelta(days=REJECTED_COOLDOWN_DAYS)).isoformat()
    with _ro_connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "meta_proposals" not in tables:  # pre-v3 DB
            return set()
        placeholders = ",".join("?" * len(_SKIP_STATUSES))
        rows = conn.execute(
            f"SELECT DISTINCT target_pattern FROM meta_proposals "
            f"WHERE status IN ({placeholders}) AND created_at >= ?",
            (*_SKIP_STATUSES, cutoff),
        ).fetchall()
    return {r["target_pattern"] for r in rows}


def _drift_patterns(db_path: Path, now: datetime) -> list[Pattern]:
    patterns: list[Pattern] = []
    for w in compute_drift_windows(db_path, now=now):
        if not w.drift_detected:
            continue
        patterns.append(
            Pattern(
                kind="drift",
                signal_id=f"drift:{w.skill_name}",
                summary=(
                    f"{w.skill_name} pass-rate dropped "
                    f"{w.prior_pass_rate:.0%} → {w.current_pass_rate:.0%} "
                    f"(Δ {w.delta:+.0%}) over the last 7 days"
                ),
                severity=min(1.0, abs(w.delta)),
                evidence={
                    "skill_name": w.skill_name,
                    "current_pass_rate": w.current_pass_rate,
                    "prior_pass_rate": w.prior_pass_rate,
                    "delta": w.delta,
                    "current_n": w.current_n,
                    "prior_n": w.prior_n,
                },
            )
        )
    return patterns


def _divergence_patterns(db_path: Path, now: datetime) -> list[Pattern]:
    d = compute_judge_human_divergence(db_path, now=now)
    if d.total_reviewed < _MIN_REVIEWED_FOR_DIVERGENCE or d.divergence_rate <= 0.0:
        return []
    return [
        Pattern(
            kind="divergence",
            signal_id="divergence:judges",
            summary=(
                f"judges disagreed with human reviewers on "
                f"{d.divergence_rate:.0%} of {d.total_reviewed} reviewed runs"
            ),
            severity=min(1.0, d.divergence_rate),
            evidence={
                "total_reviewed": d.total_reviewed,
                "judge_pass_human_fail": d.judge_pass_human_fail,
                "judge_fail_human_pass": d.judge_fail_human_pass,
                "divergence_rate": d.divergence_rate,
            },
        )
    ]


def analyze(db_path: Path, *, now: datetime | None = None) -> list[Pattern]:
    """Read-only, deterministic. Returns patterns ranked by severity (desc).

    Patterns targeted by a rejected/inconclusive proposal within the last
    REJECTED_COOLDOWN_DAYS are filtered out — no re-proposing the same thing
    week after week. Ties break on signal_id so the order is fully stable.
    """
    now = now or datetime.now(UTC)
    skipped = _recently_skipped(db_path, now)
    patterns = _drift_patterns(db_path, now) + _divergence_patterns(db_path, now)
    patterns = [p for p in patterns if p.signal_id not in skipped]
    patterns.sort(key=lambda p: (-p.severity, p.signal_id))
    return patterns
