"""meta/measure.py — post-merge attribution + auto-revert on clear regression."""

from __future__ import annotations

import json
from pathlib import Path

from memory import EpisodicMemory, SkillInvocationRecord
from meta.github_pr import OpenedPR
from meta.measure import measure_proposal, snapshot_baseline

_MERGED_AT = "2026-05-10T00:00:00+00:00"


class _FakeRevertPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def publish_revert(self, *, merge_sha: str, title: str, body: str) -> OpenedPR:
        self.calls.append({"merge_sha": merge_sha, "title": title, "body": body})
        return OpenedPR(number=99, url="https://github.com/x/y/pull/99", branch="revert")


def _seed_run(mem: EpisodicMemory, *, started_at: str, passed: bool) -> None:
    run = mem.start_run("Co", "m")
    with mem._connect() as conn:
        conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", (started_at, run.id))
    mem.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run.id,
            skill_name="draft_content_brief",
            attempt=1,
            model="claude-sonnet-4-6",
            input_json="{}",
            output_json="{}",
            eval_passed=passed,
            started_at=started_at,
        )
    )
    mem.finish_run(run.id, "completed", 1.0, "/b.md")


def _proposal(mem: EpisodicMemory) -> int:
    return mem.record_meta_proposal(
        target_pattern="drift:score_queries",
        change_type="prompt",
        hypothesis="h",
        pr_number=42,
    )


def test_snapshot_baseline_records_merge_and_before_window(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "ep.db")
    pid = _proposal(mem)
    _seed_run(mem, started_at="2026-05-05T00:00:00+00:00", passed=True)
    _seed_run(mem, started_at="2026-05-06T00:00:00+00:00", passed=False)

    snapshot_baseline(mem, pr_number=42, merged_at=_MERGED_AT, merged_sha="abc1234")

    row = mem.get_meta_proposal(pid)
    assert row["status"] == "merged"
    assert row["merged_at"] == _MERGED_AT
    snapshot = json.loads(row["baseline_window_json"])
    assert snapshot["merged_sha"] == "abc1234"
    assert sorted(snapshot["before_scores"]) == [0.0, 1.0]


def test_measure_proposal_pending_when_not_enough_after_runs(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "ep.db")
    pid = _proposal(mem)
    _seed_run(mem, started_at="2026-05-05T00:00:00+00:00", passed=True)
    snapshot_baseline(mem, pr_number=42, merged_at=_MERGED_AT, merged_sha="abc")
    _seed_run(mem, started_at="2026-05-12T00:00:00+00:00", passed=True)  # only 1 after

    outcome = measure_proposal(mem, proposal_id=pid, required_n=5)

    assert outcome.status == "merged"  # still pending — not enough data
    assert outcome.effect is None
    assert mem.get_meta_proposal(pid)["status"] == "merged"


def test_measure_proposal_marks_measured_when_not_negative(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "ep.db")
    pid = _proposal(mem)
    for _ in range(5):
        _seed_run(mem, started_at="2026-05-05T00:00:00+00:00", passed=False)  # before ~0.0
    snapshot_baseline(mem, pr_number=42, merged_at=_MERGED_AT, merged_sha="abc")
    for _ in range(5):
        _seed_run(mem, started_at="2026-05-12T00:00:00+00:00", passed=True)  # after ~1.0
    revert = _FakeRevertPublisher()

    outcome = measure_proposal(mem, proposal_id=pid, required_n=5, revert_publisher=revert)

    assert outcome.status == "measured"
    assert outcome.effect.delta > 0
    assert outcome.revert_pr_url is None
    assert revert.calls == []
    assert mem.get_meta_proposal(pid)["status"] == "measured"


def test_measure_proposal_opens_revert_pr_on_clear_regression(tmp_path: Path):
    mem = EpisodicMemory(tmp_path / "ep.db")
    pid = _proposal(mem)
    for _ in range(5):
        _seed_run(mem, started_at="2026-05-05T00:00:00+00:00", passed=True)  # before ~1.0
    snapshot_baseline(mem, pr_number=42, merged_at=_MERGED_AT, merged_sha="deadbeef")
    for _ in range(5):
        _seed_run(mem, started_at="2026-05-12T00:00:00+00:00", passed=False)  # after ~0.0
    revert = _FakeRevertPublisher()

    outcome = measure_proposal(mem, proposal_id=pid, required_n=5, revert_publisher=revert)

    assert outcome.status == "reverted"
    assert outcome.effect.delta < 0
    assert outcome.revert_pr_url == "https://github.com/x/y/pull/99"
    assert revert.calls[0]["merge_sha"] == "deadbeef"
    assert mem.get_meta_proposal(pid)["status"] == "reverted"
