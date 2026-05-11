"""select_priority_query — strategic pick of the (segment, query) to brief on.

Not pure argmax over composite — the prompt asks for judgment around
strategic fit, defensibility, and cluster-anchor potential.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ICPSegment, Priority, ScoredQueryList
from skills.base import Skill


@dataclass(frozen=True)
class SelectPriorityInputs:
    scored: ScoredQueryList
    icp_segment: ICPSegment


class SelectPriorityQuery(Skill[SelectPriorityInputs, Priority]):
    name = "select_priority_query"
    model = "claude-sonnet-4-6"
    output_type = Priority
    max_output_tokens = 2048

    def build_user_message(self, inputs: SelectPriorityInputs) -> str:
        scored_json = inputs.scored.model_dump_json(indent=2)
        return (
            f"ICP segment: {inputs.icp_segment.segment_label}\n"
            f"Buyer role: {inputs.icp_segment.persona.role_job_title}\n\n"
            f"Scored queries:\n```json\n{scored_json}\n```\n\n"
            "Pick the single priority query per the system instructions."
        )
