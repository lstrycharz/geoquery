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


# ---------------------------------------------------------------------------
# v3 chunk 5 — winning-pattern staleness signal
# ---------------------------------------------------------------------------


def test_analyze_flags_stale_winning_patterns(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    mem.record_winning_patterns(
        briefs_analyzed=10, min_eval_score=0.8, patterns=["x"], extracted_at=_iso(40)
    )
    patterns = analyze(mem.db_path, now=_NOW)
    assert [p.signal_id for p in patterns] == ["winning_patterns:stale"]
    assert patterns[0].kind == "winning_patterns_stale"


def test_analyze_does_not_flag_fresh_winning_patterns(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    mem.record_winning_patterns(
        briefs_analyzed=10, min_eval_score=0.8, patterns=["x"], extracted_at=_iso(3)
    )
    assert analyze(mem.db_path, now=_NOW) == []


def test_analyze_does_not_flag_staleness_when_never_extracted(tmp_path: Path):
    """No prior extraction = the feature was never adopted. The meta-agent
    nags about *rotted* patterns, not unused ones."""
    mem = EpisodicMemory(tmp_path / "episodic.db")
    assert analyze(mem.db_path, now=_NOW) == []


# ---------------------------------------------------------------------------
# v3 chunk 6 — escalation-cluster signal
# ---------------------------------------------------------------------------


def test_analyze_flags_escalation_cluster(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    run = mem.start_run("Acme", "project management")
    for _ in range(2):
        mem.record_escalation(
            run_id=run.id,
            skill_name="score_queries",
            attempt_failures=[["x"], ["x"], ["x"]],
            final_output_json="{}",
            escalated_at=_iso(3),
        )
    patterns = analyze(mem.db_path, now=_NOW)
    assert [p.signal_id for p in patterns] == ["escalation:score_queries"]
    assert patterns[0].evidence["escalation_count"] == 2


def test_analyze_does_not_flag_a_single_escalation(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    run = mem.start_run("Acme", "m")
    mem.record_escalation(
        run_id=run.id,
        skill_name="score_queries",
        attempt_failures=[["x"], ["x"], ["x"]],
        final_output_json="{}",
        escalated_at=_iso(3),
    )
    assert analyze(mem.db_path, now=_NOW) == []


# ---------------------------------------------------------------------------
# v3 chunk 8 — predicted-outcome signal
# ---------------------------------------------------------------------------


def _seed_predictions(mem: EpisodicMemory, *, n: int, top10: int) -> None:
    run = mem.start_run("Acme", "project management")
    for i in range(n):
        mem.record_outcome_prediction(
            run_id=run.id,
            predicted_top10=i < top10,
            confidence=0.7,
            reasoning="r",
            model="claude-opus-4-7",
            created_at=_iso(2),
        )


def test_analyze_flags_low_predicted_outcomes(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_predictions(mem, n=6, top10=1)  # ~17% top-10 rate
    patterns = analyze(mem.db_path, now=_NOW)
    assert [p.signal_id for p in patterns] == ["outcome:low_top10_rate"]


def test_analyze_no_outcome_signal_when_healthy(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_predictions(mem, n=6, top10=5)  # ~83% top-10 rate
    assert analyze(mem.db_path, now=_NOW) == []


def test_analyze_no_outcome_signal_below_min_sample(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "episodic.db")
    _seed_predictions(mem, n=3, top10=0)  # too few predictions to act on
    assert analyze(mem.db_path, now=_NOW) == []
