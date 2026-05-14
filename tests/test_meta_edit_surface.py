"""meta/edit_surface.py — the meta-agent's allowed/denied path boundary."""

from __future__ import annotations

import pytest

from meta.edit_surface import (
    EditSurfaceViolation,
    is_allowed,
    validate_paths,
)


@pytest.mark.parametrize(
    "path",
    [
        "skills/prompts/draft_content_brief.md",
        "evals/rubrics/brief_specificity.md",
        "evals/proposed/new_eval.py",
    ],
)
def test_is_allowed_accepts_edit_surface_paths(path: str):
    assert is_allowed(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "regression_dataset/notion_b2b_saas/expected.json",
        "tests/test_regression.py",
        "evals/regression.py",
        "evals/golden_set.py",
        "evals/production.py",
        "memory/schema.sql",
        ".github/workflows/regression.yml",
        "meta/edit_surface.py",
        "agent.py",
        "contracts.py",
        "config.py",
        "pyproject.toml",
    ],
)
def test_is_allowed_rejects_denied_paths(path: str):
    assert is_allowed(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "skills/base.py",
        "evals/model_graded.py",
        "cli.py",
    ],
)
def test_is_allowed_rejects_paths_outside_the_allowlist(path: str):
    """Deny-by-default: anything not under an ALLOWED prefix is rejected even
    if it isn't on the explicit denylist."""
    assert is_allowed(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "skills/prompts/../../etc/passwd",
        "/etc/passwd",
        "",
    ],
)
def test_is_allowed_rejects_path_traversal_and_absolute_paths(path: str):
    assert is_allowed(path) is False


def test_validate_paths_passes_when_all_allowed():
    validate_paths(["skills/prompts/define_icp.md", "evals/rubrics/buyer_realism.md"])


def test_validate_paths_raises_listing_the_offending_paths():
    with pytest.raises(EditSurfaceViolation) as exc:
        validate_paths(["skills/prompts/define_icp.md", "memory/schema.sql", "agent.py"])
    msg = str(exc.value)
    assert "memory/schema.sql" in msg
    assert "agent.py" in msg
    # The allowed path is not flagged.
    assert "skills/prompts/define_icp.md" not in msg
