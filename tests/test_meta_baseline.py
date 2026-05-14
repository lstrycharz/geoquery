"""meta/baseline.py — sha256 tamper detection on rubrics + denylisted evals."""

from __future__ import annotations

from pathlib import Path

from meta.baseline import (
    BASELINE_PATH,
    compute_baseline,
    load_baseline,
    verify_baseline,
)

_REPO_ROOT = Path(__file__).parent.parent


def test_compute_baseline_covers_rubrics_and_denylisted_evals():
    baseline = compute_baseline(_REPO_ROOT)
    # Every rubric is hashed.
    for rubric in (_REPO_ROOT / "evals" / "rubrics").glob("*.md"):
        assert f"evals/rubrics/{rubric.name}" in baseline
    # The denylisted eval modules are hashed.
    assert "evals/regression.py" in baseline
    assert "evals/golden_set.py" in baseline
    assert "evals/production.py" in baseline


def test_committed_baseline_is_in_sync_with_the_repo():
    """meta/baseline.json must match the current files — if this fails, someone
    changed a rubric/eval without refreshing the baseline."""
    assert BASELINE_PATH.is_file()
    assert load_baseline() == compute_baseline(_REPO_ROOT)


def test_verify_baseline_returns_empty_on_a_clean_tree():
    assert verify_baseline(_REPO_ROOT, load_baseline()) == []


def test_verify_baseline_detects_a_tampered_file():
    baseline = dict(load_baseline())
    baseline["evals/production.py"] = "0" * 64  # pretend the file changed
    changed = verify_baseline(_REPO_ROOT, baseline)
    assert changed == ["evals/production.py"]
