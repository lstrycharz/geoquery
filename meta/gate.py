"""The meta-agent CI gate — runs the meta-evals on a `meta-agent/*` PR.

Invoked by `.github/workflows/meta-agent-gate.yml`. The workflow restores
`meta/` from the base branch before running this, so the gate (and
`edit_surface.py`) is always the *trusted* copy — a meta-agent that edits its
own checks can't escape them.

Checks 3 (divergence-regression) and 5 (verbosity guard) need a production
replay over the human-review sample; they're wired in once that harness lands
(v3 chunks 7-8). The 4 diff-only checks are the hard gate today.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from meta.meta_evals import (
    MetaEvalResult,
    ProposedChange,
    cassette_integrity_check,
    protected_path_check,
    single_change_check,
    trivial_eval_check,
)

REPO_ROOT = Path(__file__).parent.parent


def proposed_change_from_git_diff(
    repo_root: Path = REPO_ROOT, base_ref: str = "origin/master"
) -> ProposedChange:
    """Build a ProposedChange from `git diff <base_ref>...HEAD`."""

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    diff_range = f"{base_ref}...HEAD"
    diff = _git("diff", diff_range)
    names = tuple(n for n in _git("diff", "--name-only", diff_range).splitlines() if n.strip())
    new_eval_paths = tuple(
        str(repo_root / n) for n in names if n.startswith("evals/proposed/") and n.endswith(".py")
    )
    return ProposedChange(edit_paths=names, diff=diff, new_eval_paths=new_eval_paths)


def run_gate(change: ProposedChange) -> tuple[bool, list[MetaEvalResult]]:
    """Run every meta-eval that can be decided from the diff alone. Returns
    (all_passed, results)."""
    results = [
        protected_path_check(change),
        trivial_eval_check(change),
        cassette_integrity_check(change),
        single_change_check(change),
    ]
    return all(r.passed for r in results), results


def main(argv: list[str] | None = None) -> int:
    change = proposed_change_from_git_diff()
    passed, results = run_gate(change)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}")
    print(f"\nmeta-agent gate: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
