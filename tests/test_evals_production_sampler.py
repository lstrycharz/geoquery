"""Production sample stream — sampler + the `human_reviews` SQLite table."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.production import maybe_sample_for_review
from memory import EpisodicMemory


@pytest.fixture
def memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "episodic.db")


@pytest.fixture
def completed_run(memory: EpisodicMemory) -> str:
    run = memory.start_run(company="Notion", market="B2B SaaS knowledge management")
    memory.finish_run(
        run_id=run.id,
        status="completed",
        total_cost_usd=0.42,
        brief_path=f"briefs/{run.id[:8]}_notion.md",
    )
    return run.id


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------


def test_sampler_with_rate_zero_never_samples(memory, completed_run):
    review_id = maybe_sample_for_review(memory, completed_run, rate=0.0)
    assert review_id is None
    assert memory.get_pending_reviews() == []


def test_sampler_with_rate_one_always_samples(memory, completed_run):
    review_id = maybe_sample_for_review(memory, completed_run, rate=1.0)
    assert review_id is not None
    pending = memory.get_pending_reviews()
    assert len(pending) == 1
    assert pending[0]["run_id"] == completed_run
    assert pending[0]["company"] == "Notion"


def test_sampler_respects_rng_below_rate(memory, completed_run):
    # 0.05 < 0.10 → sample
    rid = maybe_sample_for_review(memory, completed_run, rate=0.10, rng=lambda: 0.05)
    assert rid is not None


def test_sampler_respects_rng_above_rate(memory, completed_run):
    # 0.99 > 0.10 → do not sample
    rid = maybe_sample_for_review(memory, completed_run, rate=0.10, rng=lambda: 0.99)
    assert rid is None
    assert memory.get_pending_reviews() == []


def test_sampler_distribution_roughly_matches_rate(memory):
    """50 runs, rate=0.20 → expected mean ~10 samples with deterministic rng.
    We use seeded random.Random so this test is reproducible."""
    import random

    rng = random.Random(7)
    sampled = 0
    for i in range(50):
        run = memory.start_run(company=f"co_{i}", market="m")
        memory.finish_run(run_id=run.id, status="completed", total_cost_usd=0.1, brief_path=None)
        if maybe_sample_for_review(memory, run.id, rate=0.20, rng=rng) is not None:
            sampled += 1
    # Allow generous bounds (4-16) so the test isn't flaky in CI under
    # different Python builds, but tight enough to catch a regression
    # (e.g., always-sample or always-skip).
    assert 4 <= sampled <= 16, sampled


# ---------------------------------------------------------------------------
# human_reviews table
# ---------------------------------------------------------------------------


def test_start_human_review_creates_pending_row(memory, completed_run):
    review_id = memory.start_human_review(run_id=completed_run)
    row = memory.get_review(review_id)
    assert row is not None
    assert row["run_id"] == completed_run
    assert row["reviewed_at"] is None
    assert row["reviewer_rating_overall"] is None


def test_record_human_review_updates_in_place(memory, completed_run):
    review_id = memory.start_human_review(run_id=completed_run)
    memory.record_human_review(
        review_id=review_id,
        rating_overall=4,
        ratings_by_dim={"brand_voice": 5, "actionability": 3},
        notes="angle is sharp, but key points are abstract in section 2",
    )
    row = memory.get_review(review_id)
    assert row is not None
    assert row["reviewed_at"] is not None
    assert row["reviewer_rating_overall"] == 4
    dims = json.loads(row["reviewer_ratings_by_dim"])
    assert dims["brand_voice"] == 5
    assert "abstract" in row["reviewer_notes"]


def test_get_pending_reviews_excludes_completed(memory, completed_run):
    rid1 = memory.start_human_review(run_id=completed_run)
    # Second run, also sampled and reviewed.
    run2 = memory.start_run(company="Linear", market="B2B SaaS PM")
    memory.finish_run(run_id=run2.id, status="completed", total_cost_usd=0.5, brief_path=None)
    rid2 = memory.start_human_review(run_id=run2.id)
    memory.record_human_review(review_id=rid2, rating_overall=5)
    pending = memory.get_pending_reviews()
    assert len(pending) == 1
    assert pending[0]["id"] == rid1


def test_human_reviews_schema_version_present(memory, completed_run):
    review_id = memory.start_human_review(run_id=completed_run)
    row = memory.get_review(review_id)
    assert row is not None
    assert row["schema_version"] == 1
