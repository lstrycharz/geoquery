"""draft_content_brief — produces the final ContentBrief.

Chunk 1: placeholder version. Takes a target query + ICP segment + market and
generates a brief without SERP data or sitemap context.
Chunks 4/12 will layer in real SERP analysis + sitemap-grounded internal links.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief, ICPSegment
from skills.base import Skill


@dataclass(frozen=True)
class DraftBriefInputs:
    target_query: str
    icp_segment: ICPSegment
    market: str


class DraftContentBrief(Skill[DraftBriefInputs, ContentBrief]):
    name = "draft_content_brief"
    model = "claude-sonnet-4-6"
    output_type = ContentBrief
    max_output_tokens = 6144

    def build_user_message(self, inputs: DraftBriefInputs) -> str:
        icp_json = inputs.icp_segment.model_dump_json(indent=2)
        return (
            f"Market: {inputs.market}\n"
            f"Target query: {inputs.target_query}\n\n"
            f"Priority ICP segment:\n```json\n{icp_json}\n```\n\n"
            "Produce the ContentBrief per the system instructions."
        )
