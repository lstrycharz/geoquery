"""Model-graded evaluators — Haiku-based judges, one structured-output call each.

Two judges:
- BuyerRealismJudge: checks the GEO query list reads like real buyers, not experts.
  This is the named anti-pattern from the source GEO Query Generator skill.
- BriefSpecificityJudge: checks the content brief's angle is specific, not generic.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, Field

from contracts import BuyerJourney, ContentBrief
from evals.deterministic import EvalResult
from guardrails import RunBudget
from skills.base import estimate_cost

_JUDGE_MODEL = "claude-haiku-4-5"
_MAX_OUTPUT_TOKENS = 1024


class JudgeVerdict(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)


def _judge_call(
    *,
    client: Anthropic,
    budget: RunBudget,
    judge_name: str,
    system_prompt: str,
    user_message: str,
) -> JudgeVerdict:
    budget.check_can_spend(estimate_cost(_JUDGE_MODEL, 1500, _MAX_OUTPUT_TOKENS))
    tool_name = f"emit_{judge_name}"
    response = client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=[
            {
                "name": tool_name,
                "description": "Emit the judge's verdict.",
                "input_schema": JudgeVerdict.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    cost = estimate_cost(_JUDGE_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    budget.record_spend(cost)
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return JudgeVerdict.model_validate(block.input)
    raise RuntimeError(f"judge {judge_name} did not emit a verdict")


@dataclass
class BuyerRealismJudge:
    client: Anthropic
    budget: RunBudget
    name: str = "judge_buyer_realism"

    _SYSTEM = (
        "You evaluate whether a list of search queries reads like what a real "
        "buyer (not an expert) would actually type into a search engine. "
        "Real buyers use casual phrasing, drop filler words, type half-formed "
        "questions, and never sound like SEO professionals or domain experts. "
        "Flag any query that reads over-formal, over-polished, or expert-toned. "
        "Pass if the LIST OVERALL reads like a real buyer journey — a few "
        "over-formal items are tolerable; many are not."
    )

    def evaluate(self, output: BuyerJourney) -> EvalResult:
        numbered = "\n".join(f"{q.position}. {q.text}" for q in output.queries)
        verdict = _judge_call(
            client=self.client,
            budget=self.budget,
            judge_name=self.name,
            system_prompt=self._SYSTEM,
            user_message=(
                f"Queries to evaluate:\n{numbered}\n\n"
                "Decide pass/fail. If fail, list the over-formal queries with positions."
            ),
        )
        return EvalResult(name=self.name, passed=verdict.passed, failures=verdict.failures)


@dataclass
class BriefSpecificityJudge:
    client: Anthropic
    budget: RunBudget
    name: str = "judge_brief_specificity"

    _SYSTEM = (
        "You evaluate whether a content brief's angle is SPECIFIC and DIFFERENTIATED, "
        "or generic. A specific brief targets a named ICP with a named angle that "
        "exploits a real content gap in the SERP. A generic brief reads like "
        "'best knowledge management tools' or 'top SEO tips'. "
        "Pass if the angle, audience, and key-points all hold up to a senior "
        "content strategist's eye. Fail with concrete reasons otherwise."
    )

    def evaluate(self, output: ContentBrief) -> EvalResult:
        summary = (
            f"Target query: {output.target_query}\n"
            f"ICP segment: {output.icp_segment_label}\n"
            f"Angle: {output.angle}\n"
            f"Audience: {output.audience}\n"
            f"Top key points: {' | '.join(output.key_points[:5])}"
        )
        verdict = _judge_call(
            client=self.client,
            budget=self.budget,
            judge_name=self.name,
            system_prompt=self._SYSTEM,
            user_message=(
                f"Brief summary:\n{summary}\n\n"
                "Decide pass/fail. If fail, list specific problems with the angle or key points."
            ),
        )
        return EvalResult(name=self.name, passed=verdict.passed, failures=verdict.failures)
