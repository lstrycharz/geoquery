"""meta/gate.py — the CI gate that runs the meta-evals on a meta-agent/* PR."""

from __future__ import annotations

import subprocess
from pathlib import Path

from meta.gate import proposed_change_from_git_diff, run_gate
from meta.meta_evals import ProposedChange


def test_run_gate_passes_a_clean_single_file_prompt_edit():
    change = ProposedChange(edit_paths=("skills/prompts/score_queries.md",), diff="")
    passed, results = run_gate(change)
    assert passed is True
    assert {r.name for r in results} >= {
        "protected_path",
        "trivial_eval",
        "cassette_integrity",
        "single_change",
    }


def test_run_gate_fails_a_denied_path():
    change = ProposedChange(edit_paths=("memory/schema.sql",), diff="")
    passed, _ = run_gate(change)
    assert passed is False


def test_run_gate_fails_when_regression_dataset_touched():
    change = ProposedChange(
        edit_paths=("regression_dataset/notion_b2b_saas/expected.json",), diff=""
    )
    passed, _ = run_gate(change)
    assert passed is False


def test_run_gate_fails_a_multi_file_diff():
    change = ProposedChange(edit_paths=("skills/prompts/a.md", "skills/prompts/b.md"), diff="")
    passed, _ = run_gate(change)
    assert passed is False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_proposed_change_from_git_diff_extracts_paths_and_new_evals(tmp_path: Path):
    repo = tmp_path
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "meta-agent/x")
    (repo / "evals" / "proposed").mkdir(parents=True)
    (repo / "evals" / "proposed" / "foo.py").write_text("# new eval\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add proposed eval")

    change = proposed_change_from_git_diff(repo_root=repo, base_ref="master")

    assert "evals/proposed/foo.py" in change.edit_paths
    assert any(p.endswith("evals/proposed/foo.py") for p in change.new_eval_paths)
