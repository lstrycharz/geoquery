"""meta/github_pr.py — branch naming + PR body assembly (the pure parts)."""

from __future__ import annotations

from datetime import UTC, datetime

from meta.github_pr import branch_name, build_pr_body


def test_branch_name_is_namespaced_and_dated():
    name = branch_name("drift:score_queries", now=datetime(2026, 5, 14, tzinfo=UTC))
    assert name == "meta-agent/drift-score-queries-20260514"


def test_branch_name_slugifies_special_characters():
    name = branch_name("divergence:judges", now=datetime(2026, 1, 2, tzinfo=UTC))
    assert name.startswith("meta-agent/divergence-judges-")
    assert ":" not in name
    assert " " not in name


def test_build_pr_body_keeps_the_proposal_and_appends_reviewer_checklist():
    body = build_pr_body("# Meta-agent proposal\nthe proposal content")
    assert "the proposal content" in body
    assert "Reviewer checklist" in body
    assert "- [ ]" in body
