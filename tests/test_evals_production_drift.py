"""Drift detection + judge-vs-human divergence + Slack alert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evals.production import (
    DriftWindow,
    compute_drift_windows,
    compute_judge_human_divergence,
    post_drift_alert_to_slack,
)
from memory import EpisodicMemory, SkillInvocationRecord


@pytest.fixture
def memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "episodic.db")


def _seed_invocation(
    memory: EpisodicMemory,
    *,
    skill: str,
    started: datetime,
    passed: bool,
) -> None:
    run = memory.start_run(company="X", market="Y")
    memory.finish_run(run_id=run.id, status="completed", total_cost_usd=0.1, brief_path=None)
    memory.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run.id,
            skill_name=skill,
            attempt=1,
            model="claude-sonnet-4-6",
            input_json="{}",
            started_at=started.isoformat(),
            eval_passed=passed,
        )
    )


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def test_drift_detected_when_pass_rate_drops_below_threshold(memory):
    now = datetime.now(UTC)
    # Prior 7-day window: all 10 invocations passed (rate=1.0)
    for _ in range(10):
        _seed_invocation(
            memory, skill="analyze_serp", started=now - timedelta(days=10), passed=True
        )
    # Current 7-day window: 5/10 passed (rate=0.5; delta=-0.5)
    for i in range(10):
        passed = i < 5
        _seed_invocation(
            memory, skill="analyze_serp", started=now - timedelta(days=2), passed=passed
        )

    windows = compute_drift_windows(memory.db_path, now=now)
    assert len(windows) == 1
    w = windows[0]
    assert w.skill_name == "analyze_serp"
    assert w.current_pass_rate == 0.5
    assert w.prior_pass_rate == 1.0
    assert w.delta == -0.5
    assert w.drift_detected


def test_drift_not_detected_when_within_threshold(memory):
    now = datetime.now(UTC)
    for _ in range(10):
        _seed_invocation(memory, skill="define_icp", started=now - timedelta(days=10), passed=True)
    # 5% drop (within the -10% threshold)
    for i in range(20):
        _seed_invocation(memory, skill="define_icp", started=now - timedelta(days=2), passed=i != 0)
    windows = compute_drift_windows(memory.db_path, now=now)
    assert windows[0].drift_detected is False


def test_drift_ignores_skills_with_insufficient_samples(memory):
    """Small-N noise must not trigger an alert — require ≥5 samples per window."""
    now = datetime.now(UTC)
    # Only 3 prior + 3 current — below min_samples=5.
    for _ in range(3):
        _seed_invocation(memory, skill="rare_skill", started=now - timedelta(days=10), passed=True)
    for _ in range(3):
        _seed_invocation(memory, skill="rare_skill", started=now - timedelta(days=2), passed=False)
    windows = compute_drift_windows(memory.db_path, now=now)
    assert windows[0].drift_detected is False


def test_drift_handles_skill_with_no_prior_window(memory):
    now = datetime.now(UTC)
    # New skill appearing only in the current window — prior rate = 0.0.
    for _ in range(8):
        _seed_invocation(memory, skill="new_skill", started=now - timedelta(days=2), passed=True)
    windows = compute_drift_windows(memory.db_path, now=now)
    w = next(x for x in windows if x.skill_name == "new_skill")
    assert w.prior_n == 0
    # delta = 1.0 - 0.0 = +1.0 → not a drop, never flags drift.
    assert w.drift_detected is False


# ---------------------------------------------------------------------------
# Judge-human divergence
# ---------------------------------------------------------------------------


def test_divergence_counts_pass_vs_fail_disagreements(memory):
    now = datetime.now(UTC)
    # Reviewed run 1: judges all pass, human gives 2 → judge-pass / human-fail.
    run = memory.start_run(company="A", market="m")
    memory.finish_run(run_id=run.id, status="completed", total_cost_usd=0.1, brief_path=None)
    memory.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run.id,
            skill_name="define_icp",
            attempt=1,
            model="m",
            input_json="{}",
            started_at=now.isoformat(),
            eval_passed=True,
        )
    )
    rid = memory.start_human_review(run_id=run.id)
    memory.record_human_review(review_id=rid, rating_overall=2)
    # Reviewed run 2: a judge fails, human gives 5 → judge-fail / human-pass.
    run2 = memory.start_run(company="B", market="m")
    memory.finish_run(run_id=run2.id, status="completed", total_cost_usd=0.1, brief_path=None)
    memory.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run2.id,
            skill_name="define_icp",
            attempt=1,
            model="m",
            input_json="{}",
            started_at=now.isoformat(),
            eval_passed=False,
        )
    )
    rid2 = memory.start_human_review(run_id=run2.id)
    memory.record_human_review(review_id=rid2, rating_overall=5)
    # Reviewed run 3: agreement (judges pass, human gives 4) → no disagreement.
    run3 = memory.start_run(company="C", market="m")
    memory.finish_run(run_id=run3.id, status="completed", total_cost_usd=0.1, brief_path=None)
    memory.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run3.id,
            skill_name="define_icp",
            attempt=1,
            model="m",
            input_json="{}",
            started_at=now.isoformat(),
            eval_passed=True,
        )
    )
    rid3 = memory.start_human_review(run_id=run3.id)
    memory.record_human_review(review_id=rid3, rating_overall=4)

    div = compute_judge_human_divergence(memory.db_path, now=now)
    assert div.total_reviewed == 3
    assert div.judge_pass_human_fail == 1
    assert div.judge_fail_human_pass == 1
    assert div.divergence_rate == 2 / 3


def test_divergence_zero_when_no_reviewed_runs(memory):
    div = compute_judge_human_divergence(memory.db_path)
    assert div.total_reviewed == 0
    assert div.divergence_rate == 0.0


# ---------------------------------------------------------------------------
# Slack alert
# ---------------------------------------------------------------------------


class _SpyHttpx:
    """Capture httpx.post() calls without making a real HTTP request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, float]] = []

    def post(self, url: str, *, json: dict, timeout: float) -> None:
        self.calls.append((url, json, timeout))


def test_slack_alert_noop_when_no_drift():
    spy = _SpyHttpx()
    windows = [
        DriftWindow(
            skill_name="x",
            current_pass_rate=1.0,
            current_n=10,
            prior_pass_rate=1.0,
            prior_n=10,
            delta=0.0,
            drift_detected=False,
        )
    ]
    sent = post_drift_alert_to_slack(windows, webhook_url="https://example/x", _httpx_module=spy)
    assert sent is False
    assert spy.calls == []


def test_slack_alert_noop_when_no_webhook_configured():
    spy = _SpyHttpx()
    windows = [
        DriftWindow(
            skill_name="x",
            current_pass_rate=0.5,
            current_n=10,
            prior_pass_rate=1.0,
            prior_n=10,
            delta=-0.5,
            drift_detected=True,
        )
    ]
    sent = post_drift_alert_to_slack(windows, webhook_url="", _httpx_module=spy)
    assert sent is False
    assert spy.calls == []


def test_slack_alert_posts_when_drift_and_webhook_set():
    spy = _SpyHttpx()
    windows = [
        DriftWindow(
            skill_name="analyze_serp",
            current_pass_rate=0.5,
            current_n=10,
            prior_pass_rate=1.0,
            prior_n=10,
            delta=-0.5,
            drift_detected=True,
        )
    ]
    sent = post_drift_alert_to_slack(
        windows, webhook_url="https://hooks.slack.com/services/T/B/X", _httpx_module=spy
    )
    assert sent is True
    assert len(spy.calls) == 1
    url, body, timeout = spy.calls[0]
    assert url == "https://hooks.slack.com/services/T/B/X"
    assert "analyze_serp" in body["text"]
    assert "Δ -50%" in body["text"]
    assert timeout == 10.0
