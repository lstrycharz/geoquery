"""meta/meta_evals.py — the 6 reward-hacking checks on a meta-agent proposal."""

from __future__ import annotations

from pathlib import Path

from meta.meta_evals import (
    ProposedChange,
    _rubric_threshold_decreases,
    cassette_integrity_check,
    divergence_regression_check,
    protected_path_check,
    single_change_check,
    trivial_eval_check,
    verbosity_guard_check,
)

_PROPOSED_EVALS = Path(__file__).parent / "fixtures" / "proposed_evals"


# --- Check 1: protected-path -------------------------------------------------


def test_protected_path_check_passes_for_allowed_paths():
    change = ProposedChange(edit_paths=("skills/prompts/score_queries.md",))
    assert protected_path_check(change).passed is True


def test_protected_path_check_fails_for_denied_path():
    change = ProposedChange(edit_paths=("memory/schema.sql",))
    result = protected_path_check(change)
    assert result.passed is False
    assert "memory/schema.sql" in result.detail


def test_protected_path_check_fails_when_rubric_threshold_decreased():
    diff = (
        "--- a/evals/rubrics/brief_specificity.md\n"
        "+++ b/evals/rubrics/brief_specificity.md\n"
        "@@ -10,1 +10,1 @@\n"
        "-A brief scoring 0.8 or higher passes.\n"
        "+A brief scoring 0.6 or higher passes.\n"
    )
    change = ProposedChange(edit_paths=("evals/rubrics/brief_specificity.md",), diff=diff)
    assert protected_path_check(change).passed is False


def test_protected_path_check_allows_rubric_tightening():
    diff = (
        "--- a/evals/rubrics/brief_specificity.md\n"
        "+++ b/evals/rubrics/brief_specificity.md\n"
        "@@ -10,1 +10,1 @@\n"
        "-A brief scoring 0.6 or higher passes.\n"
        "+A brief scoring 0.8 or higher passes.\n"
    )
    change = ProposedChange(edit_paths=("evals/rubrics/brief_specificity.md",), diff=diff)
    assert protected_path_check(change).passed is True


# --- Threshold-decrease parser (named test) ----------------------------------


def test_rubric_threshold_parser_flags_a_decrease():
    diff = "+++ b/evals/rubrics/x.md\n@@\n-score 0.8 or higher\n+score 0.6 or higher\n"
    assert _rubric_threshold_decreases(diff)


def test_rubric_threshold_parser_ignores_an_increase():
    diff = "+++ b/evals/rubrics/x.md\n@@\n-score 0.6 or higher\n+score 0.8 or higher\n"
    assert _rubric_threshold_decreases(diff) == []


def test_rubric_threshold_parser_ignores_prose_only_edits():
    diff = (
        "+++ b/evals/rubrics/x.md\n@@\n-Judge the brief carefully.\n+Judge the brief rigorously.\n"
    )
    assert _rubric_threshold_decreases(diff) == []


def test_rubric_threshold_parser_flags_softened_directive():
    diff = (
        "+++ b/evals/rubrics/x.md\n"
        "@@\n"
        "-The angle MUST name a specific persona pain.\n"
        "+The angle SHOULD name a specific persona pain.\n"
    )
    assert _rubric_threshold_decreases(diff)


# --- Check 2: trivial-eval ---------------------------------------------------


def test_trivial_eval_check_passes_a_discriminating_eval():
    change = ProposedChange(
        edit_paths=("evals/proposed/good_eval.py",),
        new_eval_paths=(str(_PROPOSED_EVALS / "good_eval.py"),),
    )
    assert trivial_eval_check(change).passed is True


def test_trivial_eval_check_rejects_an_always_pass_eval():
    change = ProposedChange(
        edit_paths=("evals/proposed/always_pass_eval.py",),
        new_eval_paths=(str(_PROPOSED_EVALS / "always_pass_eval.py"),),
    )
    assert trivial_eval_check(change).passed is False


def test_trivial_eval_check_rejects_an_always_fail_eval():
    change = ProposedChange(
        edit_paths=("evals/proposed/always_fail_eval.py",),
        new_eval_paths=(str(_PROPOSED_EVALS / "always_fail_eval.py"),),
    )
    assert trivial_eval_check(change).passed is False


# --- Check 3: divergence-regression ------------------------------------------


def test_divergence_regression_check_passes_when_divergence_holds_or_drops():
    assert (
        divergence_regression_check(baseline_divergence=0.20, proposed_divergence=0.15).passed
        is True
    )


def test_divergence_regression_check_fails_when_divergence_rises():
    assert (
        divergence_regression_check(baseline_divergence=0.20, proposed_divergence=0.28).passed
        is False
    )


# --- Check 4: cassette-integrity ---------------------------------------------


def test_cassette_integrity_check_passes_when_no_dataset_touched():
    change = ProposedChange(edit_paths=("skills/prompts/score_queries.md",))
    assert cassette_integrity_check(change).passed is True


def test_cassette_integrity_check_fails_when_regression_dataset_touched():
    change = ProposedChange(edit_paths=("regression_dataset/notion_b2b_saas/expected.json",))
    assert cassette_integrity_check(change).passed is False


# --- Check 5: verbosity guard ------------------------------------------------


def test_verbosity_guard_passes_for_modest_growth():
    assert (
        verbosity_guard_check(
            baseline_median_tokens=1000, proposed_median_tokens=1100, human_rating_delta=0.0
        ).passed
        is True
    )


def test_verbosity_guard_fails_for_unbacked_bloat():
    assert (
        verbosity_guard_check(
            baseline_median_tokens=1000, proposed_median_tokens=1300, human_rating_delta=0.0
        ).passed
        is False
    )


def test_verbosity_guard_allows_bloat_backed_by_human_rating_gain():
    assert (
        verbosity_guard_check(
            baseline_median_tokens=1000, proposed_median_tokens=1300, human_rating_delta=0.5
        ).passed
        is True
    )


# --- Check 6: single-change --------------------------------------------------


def test_single_change_check_passes_for_one_file():
    change = ProposedChange(edit_paths=("skills/prompts/score_queries.md",))
    assert single_change_check(change).passed is True


def test_single_change_check_fails_for_multiple_files():
    change = ProposedChange(
        edit_paths=(
            "skills/prompts/score_queries.md",
            "evals/rubrics/brief_specificity.md",
        )
    )
    assert single_change_check(change).passed is False
