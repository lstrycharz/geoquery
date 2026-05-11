"""generate_geo_query_list — 25-query buyer journey across 5 framings.

Routed to Haiku per the source skill's non-negotiable warning: fast models
produce buyer-realistic queries; thinking models over-reason and produce
expert-sounding text that does not match how real buyers search.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import BuyerJourney, ICPSegment
from skills.base import Skill


@dataclass(frozen=True)
class GenerateQueriesInputs:
    icp_segment: ICPSegment
    market: str


class GenerateGeoQueryList(Skill[GenerateQueriesInputs, BuyerJourney]):
    name = "generate_geo_query_list"
    model = "claude-haiku-4-5"
    output_type = BuyerJourney
    max_output_tokens = 3072

    def build_user_message(self, inputs: GenerateQueriesInputs) -> str:
        seg = inputs.icp_segment
        return (
            f"Market: {inputs.market}\n"
            f"ICP segment: {seg.segment_label}\n"
            f"Buyer role: {seg.persona.role_job_title}\n"
            f"Language patterns to echo where natural: "
            f"{'; '.join(seg.persona.language_patterns)}\n"
            f"Pain points to ground queries in: "
            f"{'; '.join(seg.firmographic.strategic_pain_points)}\n\n"
            "Produce the 25-query buyer journey per the system instructions."
        )
