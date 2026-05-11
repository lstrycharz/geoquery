"""score_queries — assigns 3-axis scores (traffic, difficulty, business value)
to each query in a BuyerJourney.

Until chunk 11 lands DataForSEO, the `metrics` and `competitor_urls` fields
stay empty / null — scoring is LLM-judgment based on query patterns alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import BuyerJourney, ICPSegment, ScoredQueryList
from evals.deterministic import Evaluator, ScoredQueriesHaveValidComposites
from skills.base import Skill


@dataclass(frozen=True)
class ScoreQueriesInputs:
    journey: BuyerJourney
    icp_segment: ICPSegment


class ScoreQueries(Skill[ScoreQueriesInputs, ScoredQueryList]):
    name = "score_queries"
    model = "claude-sonnet-4-6"
    output_type = ScoredQueryList
    max_output_tokens = 4096

    def build_user_message(self, inputs: ScoreQueriesInputs) -> str:
        journey_json = inputs.journey.model_dump_json(indent=2)
        return (
            f"ICP segment: {inputs.icp_segment.segment_label}\n"
            f"Buyer role: {inputs.icp_segment.persona.role_job_title}\n"
            f"Decision criteria: {'; '.join(inputs.icp_segment.persona.decision_criteria)}\n\n"
            f"Buyer journey to score:\n```json\n{journey_json}\n```\n\n"
            "Produce one ScoredQuery per input query per the system instructions."
        )

    def make_evaluators(self) -> list[Evaluator]:
        return [ScoredQueriesHaveValidComposites()]
