"""define_icp — multi-segment firmographic + persona ICP generator."""

from __future__ import annotations

from dataclasses import dataclass

from contracts import CompanyDossier, ICPSegmentList
from evals.deterministic import Evaluator, IcpSegmentsInRange, PersonasHaveLanguagePatterns
from skills.base import Skill


@dataclass(frozen=True)
class DefineIcpInputs:
    company: str
    market: str
    company_dossier: CompanyDossier | None = None


class DefineIcp(Skill[DefineIcpInputs, ICPSegmentList]):
    name = "define_icp"
    model = "claude-sonnet-4-6"
    output_type = ICPSegmentList
    max_output_tokens = 8192  # multi-segment ICPs are verbose (2-4 segments * ~2k tokens each)

    def build_user_message(self, inputs: DefineIcpInputs) -> str:
        dossier_block = (
            "(no upstream dossier — proceed from company + market alone)"
            if inputs.company_dossier is None
            else f"```json\n{inputs.company_dossier.model_dump_json(indent=2)}\n```"
        )
        return (
            f"Company: {inputs.company}\n"
            f"Market: {inputs.market}\n\n"
            f"Upstream CompanyDossier (use as grounding, especially "
            f"customer_segments + inferred_icp + competitors):\n{dossier_block}\n\n"
            "Produce 2 to 4 distinct ICP segments per the system instructions."
        )

    def make_evaluators(self, inputs: DefineIcpInputs) -> list[Evaluator]:
        return [IcpSegmentsInRange(), PersonasHaveLanguagePatterns()]
