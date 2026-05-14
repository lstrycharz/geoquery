"""Edit-surface enforcement — what the meta-agent is allowed to touch.

The meta-agent optimizes eval scores; left unconstrained it will edit the
graders, the regression baselines, or its own allowlist. This module is the
security boundary: a deny-by-default path validator.

The CI gate (chunk 4) re-runs this check using a copy of this file checked
out from `main` — never from the PR head — so a meta-agent that edits its
own allowlist is caught by the trusted copy.
"""

from __future__ import annotations

from collections.abc import Iterable

# The meta-agent may only propose changes under these prefixes:
#   skills/prompts/  — prompt edits
#   evals/rubrics/   — rubric tightenings (the CI gate enforces "tighten only")
#   evals/proposed/  — net-new evals; a human wires them in on merge
ALLOWED_PREFIXES: tuple[str, ...] = (
    "skills/prompts/",
    "evals/rubrics/",
    "evals/proposed/",
)

# Explicitly hard-denied. With deny-by-default these are already excluded
# (they sit under no ALLOWED prefix), but an explicit denylist makes the
# intent legible and lets the violation message name the protected asset.
DENIED_PREFIXES: tuple[str, ...] = (
    "regression_dataset/",
    "tests/",
    "evals/regression.py",
    "evals/golden_set.py",
    "evals/production.py",
    "memory/",
    ".github/",
    "meta/",
    "agent.py",
    "contracts.py",
    "config.py",
    "pyproject.toml",
)


class EditSurfaceViolation(ValueError):
    """Raised when a proposed path is outside the meta-agent's edit surface."""


def _normalize(path: str) -> str:
    return path.strip().lstrip("./")


def is_allowed(path: str) -> bool:
    """True iff `path` is inside the meta-agent's edit surface.

    Deny-by-default: a path must match an ALLOWED prefix, must not match a
    DENIED prefix, and must not be absolute or escape the repo via traversal.
    """
    norm = _normalize(path)
    if not norm or path.strip().startswith("/") or ".." in norm.split("/"):
        return False
    if any(norm.startswith(d) for d in DENIED_PREFIXES):
        return False
    return any(norm.startswith(a) for a in ALLOWED_PREFIXES)


def validate_paths(paths: Iterable[str]) -> None:
    """Raise EditSurfaceViolation naming every path outside the edit surface."""
    bad = sorted(p for p in paths if not is_allowed(p))
    if bad:
        raise EditSurfaceViolation(
            "proposed change touches paths outside the meta-agent edit surface: " + ", ".join(bad)
        )
