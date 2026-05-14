"""Tamper detection on the grading logic.

`baseline.json` holds sha256 hashes of every rubric and every denylisted eval
module. The CI gate (chunk 4) re-computes them against the PR tree; a mismatch
on a denylisted eval module means the meta-agent altered grading logic it is
not allowed to touch. Rubrics *are* on the edit-surface allowlist (tighten-
only), so they're hashed mainly so the committed snapshot stays honest — a
rubric edit must come with a refreshed baseline.

The committed `baseline.json` is the trusted snapshot; it lives under `meta/`,
which is itself on the meta-agent's denylist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASELINE_PATH = Path(__file__).parent / "baseline.json"

# Eval modules the meta-agent must never be able to silently change. These are
# the denylisted eval files — the graders and the regression machinery.
_HASHED_DENYLISTED_EVALS: tuple[str, ...] = (
    "evals/regression.py",
    "evals/golden_set.py",
    "evals/production.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_baseline(repo_root: Path) -> dict[str, str]:
    """Map of repo-relative path -> sha256 for every rubric + denylisted eval."""
    out: dict[str, str] = {}
    for rubric in sorted((repo_root / "evals" / "rubrics").glob("*.md")):
        out[f"evals/rubrics/{rubric.name}"] = _sha256(rubric)
    for rel in _HASHED_DENYLISTED_EVALS:
        out[rel] = _sha256(repo_root / rel)
    return out


def write_baseline(repo_root: Path, path: Path = BASELINE_PATH) -> None:
    """(Re)generate the committed snapshot. Run this deliberately when a rubric
    is intentionally tightened."""
    payload = json.dumps(compute_baseline(repo_root), indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_baseline(repo_root: Path, baseline: dict[str, str]) -> list[str]:
    """Return the sorted list of baseline-tracked files whose current hash no
    longer matches the snapshot (empty == clean tree)."""
    current = compute_baseline(repo_root)
    return sorted(rel for rel, digest in baseline.items() if current.get(rel) != digest)
