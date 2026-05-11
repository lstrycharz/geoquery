"""Skill base class — the contract every skill module fulfills.

A Skill is a deep module with one public method, `.run(inputs) -> SkillResult`.
Internally it owns: a prompt template, a Pydantic output type, a model choice,
and (added in chunk 6) a list of evaluators. The base class enforces:

- Anthropic structured outputs via forced tool use (the output Pydantic type's
  JSON schema is the tool's input schema; the model is forced to call it).
- Prompt caching on the static system prompt via `cache_control: ephemeral`.
- Budget accounting (cost cap + retry cap) before and after every call.
- Eval + inner-loop revision hooks (stubbed here; wired in chunk 6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from guardrails import RunBudget

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)


PROMPTS_DIR = Path(__file__).parent / "prompts"


# Pricing per million tokens (USD), approximate Claude 4.X public pricing.
# Used to charge the RunBudget after each call.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.80, 4.00),
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

    def run(self, inputs: InputT) -> SkillResult[OutputT]:
        attempt = self.budget.register_attempt(self.name)
        self.budget.check_can_spend(self._projected_cost())

        tool_name = f"emit_{self.name}"
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
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
