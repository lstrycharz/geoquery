"""Skill base class — the contract every skill module fulfills.

A Skill is a deep module with one public method, `.run(inputs) -> SkillResult`.
Internally it owns: a prompt template, a Pydantic output type, a model choice,
and a list of evaluators (chunk 6+). The base class enforces:

- Anthropic structured outputs via forced tool use (the output Pydantic type's
  JSON schema is the tool's input schema; the model is forced to call it).
- Prompt caching on the static system prompt via `cache_control: ephemeral`.
- Budget accounting (cost cap + retry cap) before and after every call.
- Eval + inner-loop revision: on eval failure, re-run with feedback prepended
  to the system prompt as a non-cached revision block. Bounded by retry cap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from guardrails import RunBudget

if TYPE_CHECKING:
    from evals.deterministic import Evaluator

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)


PROMPTS_DIR = Path(__file__).parent / "prompts"


# Pricing per million tokens (USD), approximate Claude 4.X public pricing.
# Used to charge the RunBudget after each call.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # Aliases and versioned IDs both supported by the Messages API; map both.
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in _PRICE_PER_MTOK:
        raise ValueError(f"unknown model pricing: {model}")
    in_price, out_price = _PRICE_PER_MTOK[model]
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def load_prompt(skill_name: str) -> str:
    path = PROMPTS_DIR / f"{skill_name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt template missing: {path}")
    return path.read_text(encoding="utf-8")


@dataclass
class SkillResult(Generic[OutputT]):
    output: OutputT
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    attempt: int
    eval_passed: bool = True
    eval_failures: list[str] = field(default_factory=list)


class Skill(ABC, Generic[InputT, OutputT]):
    name: ClassVar[str]
    model: ClassVar[str]
    output_type: ClassVar[type[BaseModel]]
    max_output_tokens: ClassVar[int] = 4096

    def __init__(self, client: Anthropic, budget: RunBudget) -> None:
        self.client = client
        self.budget = budget

    @abstractmethod
    def build_user_message(self, inputs: InputT) -> str:
        """Render the dynamic, per-call user message from typed inputs."""

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.name)

    def make_evaluators(self) -> list[Evaluator]:
        """Subclasses override to declare deterministic + model-graded evaluators.

        Default: no evaluators (skill returns whatever the model emits).
        """
        return []

    def run(self, inputs: InputT) -> SkillResult[OutputT]:
        """Public entry: runs the skill and applies the inner-loop revision
        if any *blocking* evaluators fail. Advisory evaluators (model-graded
        judges) surface their failures in the result but do not gate the loop.
        Bounded by RunBudget.register_attempt's retry cap.
        """
        evaluators = self.make_evaluators()
        revision_feedback: list[str] = []
        while True:
            result = self._invoke_once(inputs, revision_feedback)
            blocking_failures: list[str] = []
            advisory_failures: list[str] = []
            for ev in evaluators:
                er = ev.evaluate(result.output)
                if er.passed:
                    continue
                bucket = blocking_failures if getattr(ev, "blocking", True) else advisory_failures
                bucket.extend(f"[{er.name}] {msg}" for msg in er.failures)
            if not blocking_failures:
                # Pipeline proceeds. Advisory failures are recorded but not
                # treated as failures for purposes of eval_passed (which gates
                # downstream consumers / episodic-log "did this skill pass?").
                result.eval_passed = True
                result.eval_failures = [f"[ADVISORY] {f}" for f in advisory_failures]
                return result
            result.eval_passed = False
            result.eval_failures = blocking_failures + [
                f"[ADVISORY] {f}" for f in advisory_failures
            ]
            # Only blocking failures feed the revision header — advisory ones
            # would distract the model with irrelevant instructions.
            revision_feedback = blocking_failures

    def _invoke_once(
        self, inputs: InputT, revision_feedback: list[str]
    ) -> SkillResult[OutputT]:
        attempt = self.budget.register_attempt(self.name)
        self.budget.check_can_spend(self._projected_cost())

        system_blocks: list[dict] = []
        if revision_feedback:
            system_blocks.append(
                {
                    "type": "text",
                    "text": _format_revision_header(revision_feedback, attempt),
                    # No cache_control — revision header is dynamic per attempt.
                }
            )
        system_blocks.append(
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        )

        tool_name = f"emit_{self.name}"
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=system_blocks,
            messages=[
                {"role": "user", "content": self.build_user_message(inputs)},
            ],
            tools=[
                {
                    "name": tool_name,
                    "description": f"Emit the structured output for the {self.name} skill.",
                    "input_schema": self.output_type.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )

        cost = estimate_cost(self.model, response.usage.input_tokens, response.usage.output_tokens)
        self.budget.record_spend(cost)

        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"skill {self.name!r} hit max_output_tokens={self.max_output_tokens} "
                f"mid-generation; tool_use input is incomplete. Raise the skill's "
                f"max_output_tokens class var."
            )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                try:
                    parsed = self.output_type.model_validate(block.input)
                except ValidationError as e:
                    raise RuntimeError(
                        f"skill {self.name} returned output that failed contract validation: {e}"
                    ) from e
                return SkillResult(
                    output=parsed,  # type: ignore[arg-type]
                    model=self.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost_usd=cost,
                    attempt=attempt,
                )

        raise RuntimeError(f"skill {self.name} did not emit a {tool_name} tool_use block")

    def _projected_cost(self) -> float:
        """Rough upper bound used by the budget pre-check.

        Assumes max_output_tokens are spent (worst case) and a 4k-token system
        prompt. Cheap to overestimate — the actual cost is recorded afterward.
        """
        return estimate_cost(self.model, 4000, self.max_output_tokens)


def _format_revision_header(failures: list[str], attempt: int) -> str:
    bulleted = "\n".join(f"- {f}" for f in failures)
    return (
        f"[REVISION ATTEMPT {attempt}]\n"
        f"The previous output failed these checks:\n"
        f"{bulleted}\n\n"
        f"Re-do the task, addressing each failure specifically. Do not repeat the "
        f"mistakes named above.\n\n"
        f"---\n"
    )
