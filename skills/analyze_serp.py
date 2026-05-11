"""analyze_serp — synthesizes a SerpAnalysis from the top SERP results.

Chunk 4: works on snippets only (URLs + titles + snippets from web_search).
Chunk 10 will add `extracted_content` per result via tools/web_fetch.py;
the prompt already references "in chunk 10 these will also carry extracted
body content" so the skill upgrades cleanly without a contract change.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import SerpAnalysis, SerpResult
from evals.deterministic import AnalyzeSerpStructure, Evaluator
from skills.base import Skill


@dataclass(frozen=True)
class AnalyzeSerpInputs:
    query_text: str
    serp_results: list[SerpResult]


class AnalyzeSerp(Skill[AnalyzeSerpInputs, SerpAnalysis]):
    name = "analyze_serp"
    model = "claude-sonnet-4-6"
    output_type = SerpAnalysis
    max_output_tokens = 2048

    def build_user_message(self, inputs: AnalyzeSerpInputs) -> str:
        results_block = "\n\n".join(
            f"#{r.rank} {r.title}\n{r.url}\n{r.snippet}"
            for r in inputs.serp_results
        )
        return (
            f"Query: {inputs.query_text}\n\n"
            f"Top SERP results:\n{results_block}\n\n"
            "Produce the SerpAnalysis per the system instructions."
        )

    def make_evaluators(self) -> list[Evaluator]:
        return [AnalyzeSerpStructure()]
