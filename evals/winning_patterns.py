"""Winning-patterns extractor — Mechanism 2's structural-learning step.

A periodic LLM call (weekly, via `geoquery extract-patterns`) reads the top-N
highest-scoring briefs and distills the *structural* patterns they share —
"high-scorers name a specific persona pain in the angle; 5-6 sections; ...".
The result is cached in the `winning_patterns` table; the drafter injects the
latest row as guidance on every run.

This is deliberately not per-run: it's a slow-moving signal, and an LLM call
on every brief would be wasteful. The few-shot examples carry the *shape* of
nearby briefs; these patterns carry the *deep lessons* from the best ones.
"""

from __future__ import annotations

from anthropic import Anthropic
from pydantic import BaseModel

from guardrails import RunBudget
from memory import EpisodicMemory, SemanticMemory
from skills.base import estimate_cost

_EXTRACTOR_MODEL = "claude-sonnet-4-6"
_MAX_OUTPUT_TOKENS = 1024

_SYSTEM_PROMPT = (
    "You analyze a corpus of high-performing SEO content briefs and extract the "
    "STRUCTURAL patterns they share — the repeatable shape, not the topic. Each "
    "pattern must be a single concrete, actionable sentence a brief writer could "
    "follow (e.g. 'the angle names a specific persona pain, not a category "
    "benefit'). Emit 3-6 patterns. Do not restate any brief's content; "
    "generalize across them."
)


class WinningPatternsExtraction(BaseModel):
    patterns: list[str]


def extract_winning_patterns(
    *,
    semantic: SemanticMemory,
    episodic: EpisodicMemory,
    client: Anthropic,
    budget: RunBudget,
    top_n: int = 10,
) -> list[str]:
    """Distill structural patterns from the top-N highest-scoring briefs and
    cache them in `winning_patterns`. No briefs scored yet → no-op (returns [])."""
    briefs = semantic.top_scoring_briefs(limit=top_n)
    if not briefs:
        return []

    corpus = "\n\n".join(
        f"[brief {i + 1} — eval_score {b.eval_score:.2f}]\n"
        f"market: {b.market}\n"
        f"icp: {b.icp_summary}\n"
        f"angle: {b.angle}\n"
        f"sections: {b.section_skeleton or '(skeleton not recorded)'}"
        for i, b in enumerate(briefs)
    )
    user_message = (
        f"Here are the {len(briefs)} highest-scoring briefs in the corpus.\n\n"
        f"{corpus}\n\n"
        "Extract the structural patterns they share."
    )

    budget.check_can_spend(estimate_cost(_EXTRACTOR_MODEL, 2500, _MAX_OUTPUT_TOKENS))
    tool_name = "emit_winning_patterns"
    response = client.messages.create(
        model=_EXTRACTOR_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        tools=[
            {
                "name": tool_name,
                "description": "Emit the extracted structural patterns.",
                "input_schema": WinningPatternsExtraction.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    cost = estimate_cost(
        _EXTRACTOR_MODEL, response.usage.input_tokens, response.usage.output_tokens
    )
    budget.record_spend(cost)

    extraction: WinningPatternsExtraction | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            extraction = WinningPatternsExtraction.model_validate(block.input)
            break
    if extraction is None:
        raise RuntimeError("winning-patterns extractor did not emit a result")

    episodic.record_winning_patterns(
        briefs_analyzed=len(briefs),
        min_eval_score=min(b.eval_score for b in briefs),
        patterns=extraction.patterns,
    )
    return extraction.patterns
