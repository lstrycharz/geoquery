"""define_icp — multi-segment firmographic + persona ICP generator."""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ICPSegmentList
from evals.deterministic import Evaluator, IcpSegmentsInRange, PersonasHaveLanguagePatterns
from skills.base import Skill


@dataclass(frozen=True)
class DefineIcpInputs:
    company: str
    market: str


class DefineIcp(Skill[DefineIcpInputs, ICPSegmentList]):
    name = "define_icp"
    model = "claude-sonnet-4-6"
    output_type = ICPSegmentList
    max_output_tokens = 4096

    def build_user_message(self, inputs: DefineIcpInputs) -> str:
        return (
            f"Company: {inputs.company}\n"
            f"Market: {inputs.market}\n\n"
            "Produce 2 to 4 distinct ICP segments per the system instructions."
        )

    def make_evaluators(self) -> list[Evaluator]:
        return [IcpSegmentsInRange(), PersonasHaveLanguagePatterns()]
