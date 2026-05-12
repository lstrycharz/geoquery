"""Model-graded evaluators — Haiku-based judges, one structured-output call each.

Judges:
- BuyerRealismJudge: checks the GEO query list reads like real buyers, not experts.
  This is the named anti-pattern from the source GEO Query Generator skill.
- BriefSpecificityJudge: checks the content brief's angle is specific, not generic.

Rubric prompts live in evals/rubrics/*.md and are loaded via rubric_loader so
PR diffs show prose changes, not Python-string changes. Mirrors skills/prompts/.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, Field

from contracts import BuyerJourney, CompanyDossier, ContentBrief
from evals.deterministic import EvalResult
from evals.rubric_loader import load_rubric
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
    # Judges are advisory: their failures surface in the episodic log but do
    # not gate the run. Deterministic checks are the blocking gate.
    blocking: bool = False
    # Rubric name resolves to evals/rubrics/{rubric}.md. Field, not class const,
    # so callers can A/B alternate rubrics in evals without monkeypatching.
    rubric: str = "buyer_realism"

    def evaluate(self, output: BuyerJourney) -> EvalResult:
        numbered = "\n".join(f"{q.position}. {q.text}" for q in output.queries)
        verdict = _judge_call(
            client=self.client,
            budget=self.budget,
            judge_name=self.name,
            system_prompt=load_rubric(self.rubric),
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
    blocking: bool = False
    rubric: str = "brief_specificity"

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
            system_prompt=load_rubric(self.rubric),
            user_message=(
                f"Brief summary:\n{summary}\n\n"
                "Decide pass/fail. List specific problems with the angle or key points if fail."
            ),
        )
        return EvalResult(name=self.name, passed=verdict.passed, failures=verdict.failures)


@dataclass
class BrandVoiceMatchJudge:
    """Judges whether the brief's register matches the dossier's brand voice.

    The dossier is baked in at construction time (via `make_evaluators(inputs)`
    in the drafter skill) so this judge satisfies the standard Evaluator
    protocol — `evaluate(brief)` like every other content-brief evaluator.
    Pure tone judgement; content quality is judged by BriefSpecificityJudge.
    """

    client: Anthropic
    budget: RunBudget
    dossier: CompanyDossier
    name: str = "judge_brand_voice_match"
    blocking: bool = False
    rubric: str = "brand_voice_match"

    def evaluate(self, output: ContentBrief) -> EvalResult:
        dossier_block = (
            f"Customer segments: {' | '.join(self.dossier.customer_segments[:4])}\n"
            f"Inferred ICP: {self.dossier.inferred_icp}\n"
            f"Company advantages: {' | '.join(self.dossier.company_advantages[:5])}\n"
            f"ICP priorities: {' | '.join(self.dossier.icp_priorities[:5])}"
        )
        brief_block = (
            f"Angle: {output.angle}\n"
            f"Audience: {output.audience}\n"
            f"Top key points: {' | '.join(output.key_points[:5])}"
        )
        verdict = _judge_call(
            client=self.client,
            budget=self.budget,
            judge_name=self.name,
            system_prompt=load_rubric(self.rubric),
            user_message=(
                f"Dossier signals:\n{dossier_block}\n\n"
                f"Brief to evaluate:\n{brief_block}\n\n"
                "Decide pass/fail per the rubric. If fail, name off-brand phrases."
            ),
        )
        return EvalResult(name=self.name, passed=verdict.passed, failures=verdict.failures)
