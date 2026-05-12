"""score_queries — assigns 3-axis scores (traffic, difficulty, business value)
to each query in a BuyerJourney.

Until chunk 11 lands DataForSEO, the `metrics` and `competitor_urls` fields
stay empty / null — scoring is LLM-judgment based on query patterns alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import BuyerJourney, ICPSegment, KeywordMetrics, ScoredQueryList
from evals.deterministic import Evaluator, ScoredQueriesHaveValidComposites
from skills.base import Skill


@dataclass(frozen=True)
class ScoreQueriesInputs:
    journey: BuyerJourney
    icp_segment: ICPSegment
    keyword_metrics: dict[str, KeywordMetrics] | None = None


class ScoreQueries(Skill[ScoreQueriesInputs, ScoredQueryList]):
    name = "score_queries"
    model = "claude-sonnet-4-6"
    output_type = ScoredQueryList
    max_output_tokens = 8192  # 25 scored queries + per-query rationales

    def build_user_message(self, inputs: ScoreQueriesInputs) -> str:
        journey_json = inputs.journey.model_dump_json(indent=2)
        metrics_block = self._metrics_block(inputs.keyword_metrics)
        return (
            f"ICP segment: {inputs.icp_segment.segment_label}\n"
            f"Buyer role: {inputs.icp_segment.persona.role_job_title}\n"
            f"Decision criteria: {'; '.join(inputs.icp_segment.persona.decision_criteria)}\n\n"
            f"Buyer journey to score:\n```json\n{journey_json}\n```\n\n"
            f"{metrics_block}\n"
            "Produce one ScoredQuery per input query per the system instructions.\n"
            "Use the real metrics where provided; estimate (and say so in the "
            "rationale) where they're absent. Copy the real volume/KD/CPC into "
            "the `metrics` field of the corresponding ScoredQuery."
        )

    @staticmethod
    def _metrics_block(metrics: dict[str, KeywordMetrics] | None) -> str:
        if not metrics:
            return (
                "Real keyword metrics: (none — DataForSEO not configured; "
                "score traffic/difficulty by LLM judgment alone)"
            )
        lines = ["Real keyword metrics (DataForSEO):"]
        for query, m in metrics.items():
            bits = []
            if m.volume is not None:
                bits.append(f"volume={m.volume}")
            if m.kd is not None:
                bits.append(f"kd={m.kd:.1f}")
            if m.cpc is not None:
                bits.append(f"cpc=${m.cpc:.2f}")
            if bits:
                lines.append(f"  - {query!r}: {', '.join(bits)}")
        return "\n".join(lines)

    def make_evaluators(self, inputs: ScoreQueriesInputs) -> list[Evaluator]:
        return [ScoredQueriesHaveValidComposites()]
