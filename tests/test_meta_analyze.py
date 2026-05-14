"""meta/analyze.py — rule-based, deterministic, read-only pattern detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from memory import EpisodicMemory, SkillInvocationRecord
from meta.analyze import Pattern, analyze

_NOW = datetime(2026, 5, 14, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


def _seed_invocation(
    mem: EpisodicMemory,
    run_id: str,
    skill: str,
    *,
    days_ago: float,
    passed: bool,
) -> None:
    mem.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run_id,
            skill_name=skill,
            attempt=1,
            model="claude-sonnet-4-6",
            input_json="{}",
            output_json="{}",
            eval_passed=passed,
            eval_details_json=None if passed else '["fail"]',
            started_at=_iso(days_ago),
        )
    )


def _seed_drift(mem: EpisodicMemory, skill: str, *, current_pass: int, prior_pass: int) -> str:
    """6 invocations in the last 7d (current_pass of them passing) and 6 in the
    prior 7d window (prior_pass passing)."""
    run = mem.start_run(company="Acme", market="m")
    for i in range(6):
        _seed_invocation(mem, run.id, skill, days_ago=3, passed=i < current_pass)
    for i in range(6):
        _seed_invocation(mem, run.id, skill, days_ago=10, passed=i < prior_pass)
    return run.id


def test_analyze_returns_empty_on_clean_db(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_drift(mem, "score_queries", current_pass=6, prior_pass=6)  # no drop → no pattern
    assert analyze(mem.db_path, now=_NOW) == []


def test_analyze_detects_drift_pattern(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_drift(mem, "score_queries", current_pass=2, prior_pass=6)  # 33% vs 100%

    patterns = analyze(mem.db_path, now=_NOW)
    assert len(patterns) == 1
    assert isinstance(patterns[0], Pattern)
    assert patterns[0].kind == "drift"
    assert patterns[0].signal_id == "drift:score_queries"
    assert patterns[0].evidence["skill_name"] == "score_queries"


def test_analyze_is_deterministic(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_drift(mem, "score_queries", current_pass=2, prior_pass=6)
    _seed_drift(mem, "analyze_serp", current_pass=3, prior_pass=6)

    first = analyze(mem.db_path, now=_NOW)
    second = analyze(mem.db_path, now=_NOW)
    assert first == second


def test_analyze_ranks_by_severity_descending(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    # score_queries drops 100%→33% (Δ-0.67); analyze_serp drops 100%→50% (Δ-0.50).
    _seed_drift(mem, "score_queries", current_pass=2, prior_pass=6)
    _seed_drift(mem, "analyze_serp", current_pass=3, prior_pass=6)

    patterns = analyze(mem.db_path, now=_NOW)
    assert [p.signal_id for p in patterns] == ["drift:score_queries", "drift:analyze_serp"]


def test_analyze_skips_recently_rejected_pattern(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_drift(mem, "score_queries", current_pass=2, prior_pass=6)
    # A proposal targeting this exact signal was rejected 3 days ago — don't
    # re-propose it this week.
    mem.record_meta_proposal(
        target_pattern="drift:score_queries",
        change_type="prompt",
        hypothesis="x",
        status="rejected",
        created_at=_iso(3),
    )
    assert analyze(mem.db_path, now=_NOW) == []


def test_analyze_does_not_skip_old_rejected_pattern(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_drift(mem, "score_queries", current_pass=2, prior_pass=6)
    # Rejected 40 days ago — past the 30-day cooldown, so it's fair game again.
    mem.record_meta_proposal(
        target_pattern="drift:score_queries",
        change_type="prompt",
        hypothesis="x",
        status="rejected",
        created_at=_iso(40),
    )
    patterns = analyze(mem.db_path, now=_NOW)
    assert [p.signal_id for p in patterns] == ["drift:score_queries"]
