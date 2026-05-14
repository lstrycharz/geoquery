"""The meta-agent's single LLM call — turns one Pattern into one Proposal.

Anti-Goodhart boundary: `propose` is NEVER shown the rubric prose of the
judges it is optimizing against. It sees the *pattern* (what regressed) and
the *actual skill outputs* (the work) — never the grader's text. If it could
read the rubric it would optimize against the rubric; seeing only outputs
forces it to improve the actual work.

It is also a *single* LLM call by design — one diff, one hypothesis, one
predicted effect — so a human reviews exactly one bounded change.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from pydantic import BaseModel, Field

from guardrails import RunBudget
from meta.analyze import Pattern
from meta.edit_surface import ALLOWED_PREFIXES, validate_paths
from skills.base import estimate_cost

_PROPOSE_MODEL = "claude-sonnet-4-6"
_MAX_OUTPUT_TOKENS = 2048
_SAMPLE_OUTPUTS_LIMIT = 5

_SYSTEM_PROMPT = (
    "You are the meta-agent for a content-brief pipeline. You are given ONE "
    "systematic pattern detected in the pipeline's eval history, plus recent "
    "real outputs of the affected work. Propose exactly ONE small, bounded "
    "change that addresses the root cause.\n\n"
    "You may ONLY edit files under these prefixes:\n"
    + "\n".join(f"  - {p}" for p in ALLOWED_PREFIXES)
    + "\n\nRules:\n"
    "- Improve the actual work, not the way it is graded.\n"
    "- One logical change only: one prompt edit OR one new example OR one new "
    "eval. Never several at once.\n"
    "- rubric edits may only TIGHTEN (raise a bar), never loosen.\n"
    "- Emit a unified diff, a one-paragraph hypothesis, the predicted effect, "
    "and the exact list of file paths your diff touches."
)


class ProposalDraft(BaseModel):
    """The LLM's structured output."""

    change_type: str = Field(description="one of: prompt | rubric | eval | fewshot")
    hypothesis: str
    diff: str
    predicted_effect: str
    edit_paths: list[str]


@dataclass(frozen=True)
class Proposal:
    """A validated, edit-surface-checked change ready to become a PR (chunk 4)."""

    target_pattern: str  # the Pattern.signal_id this addresses
    change_type: str
    hypothesis: str
    diff: str
    predicted_effect: str
    edit_paths: tuple[str, ...]


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sample_outputs(db_path: Path, pattern: Pattern) -> list[str]:
    """Recent real outputs of the work this pattern is about.

    A drift pattern names a skill; sample that skill's outputs. Anything else
    (e.g. judge divergence) has no single skill — fall back to the drafter's
    output, since the brief is the pipeline's end product.
    """
    skill_name = pattern.evidence.get("skill_name") or "draft_content_brief"
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT output_json FROM skill_invocations "
            "WHERE skill_name = ? AND output_json IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (skill_name, _SAMPLE_OUTPUTS_LIMIT),
        ).fetchall()
    return [r["output_json"] for r in rows]


def _build_context(pattern: Pattern, db_path: Path) -> str:
    """The user message handed to the model.

    Carries the pattern + the affected skill's actual recent outputs. It must
    NOT read or include any file from evals/rubrics/ — see module docstring.
    """
    samples = _sample_outputs(db_path, pattern)
    sample_block = (
        "\n\n".join(f"[output {i + 1}]\n{s}" for i, s in enumerate(samples))
        if samples
        else "(no recent outputs recorded for the affected skill)"
    )
    return (
        f"Detected pattern ({pattern.kind}):\n{pattern.summary}\n\n"
        f"Evidence:\n{json.dumps(pattern.evidence, indent=2, sort_keys=True)}\n\n"
        f"Recent real outputs of the affected work:\n{sample_block}\n\n"
        "Propose one bounded change."
    )


def propose(
    pattern: Pattern,
    *,
    client: Anthropic,
    budget: RunBudget,
    db_path: Path,
) -> Proposal:
    """Single LLM call: Pattern -> validated Proposal.

    Raises EditSurfaceViolation if the model proposes a path outside the
    meta-agent's edit surface — we abort before opening a doomed PR.
    """
    budget.check_can_spend(estimate_cost(_PROPOSE_MODEL, 3000, _MAX_OUTPUT_TOKENS))
    tool_name = "emit_meta_proposal"
    response = client.messages.create(
        model=_PROPOSE_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_context(pattern, db_path)}],
        tools=[
            {
                "name": tool_name,
                "description": "Emit the meta-agent's single proposed change.",
                "input_schema": ProposalDraft.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    cost = estimate_cost(_PROPOSE_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    budget.record_spend(cost)

    draft: ProposalDraft | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            draft = ProposalDraft.model_validate(block.input)
            break
    if draft is None:
        raise RuntimeError("propose: model did not emit a proposal")

    # UX guard: reject an out-of-surface proposal here, before a PR is opened.
    # The CI gate re-checks with edit_surface.py from `main` — this is the
    # fast-fail copy, not the security boundary.
    validate_paths(draft.edit_paths)

    return Proposal(
        target_pattern=pattern.signal_id,
        change_type=draft.change_type,
        hypothesis=draft.hypothesis,
        diff=draft.diff,
        predicted_effect=draft.predicted_effect,
        edit_paths=tuple(draft.edit_paths),
    )
