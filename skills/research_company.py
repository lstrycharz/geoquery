"""research_company — CASINO-format strategic dossier.

Runs first in the pipeline (chunk 9). Provides empirically-grounded company
context that define_icp consumes to ground its ICP segments. Without this,
ICP segments are inferred from the company name + market alone; with it,
they're built on top of an 11-section strategic analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import CompanyDossier
from evals.deterministic import Evaluator
from skills.base import Skill


@dataclass(frozen=True)
class ResearchCompanyInputs:
    company: str
    market: str


class ResearchCompany(Skill[ResearchCompanyInputs, CompanyDossier]):
    name = "research_company"
    model = "claude-sonnet-4-6"
    output_type = CompanyDossier
    max_output_tokens = 8192  # 11-section dossier, lists per section

    def build_user_message(self, inputs: ResearchCompanyInputs) -> str:
        return (
            f"Company: {inputs.company}\n"
            f"Market: {inputs.market}\n\n"
            "Produce the 11-section CompanyDossier per the system instructions."
        )

    def make_evaluators(self) -> list[Evaluator]:
        from evals.deterministic import CompanyDossierComplete

        return [CompanyDossierComplete()]
