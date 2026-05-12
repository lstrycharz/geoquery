"""draft_content_brief — produces the final ContentBrief.

Chunk 5: now SERP-informed. Inputs include a SerpAnalysis whose common_angles
and content_gaps drive the brief's differentiation. SerpAnalysis is optional
so older direct callers (e.g. unit tests pre-chunk-4) keep working.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief, ICPSegment, SerpAnalysis
from evals.deterministic import BriefStructure, DraftAngleNonEmpty, Evaluator
from evals.model_graded import BriefSpecificityJudge
from memory import SimilarBrief
from skills.base import Skill
from tools.sitemap_parser import SitemapEntry


@dataclass(frozen=True)
class DraftBriefInputs:
    target_query: str
    icp_segment: ICPSegment
    market: str
    serp_analysis: SerpAnalysis | None = None
    similar_past_briefs: tuple[SimilarBrief, ...] = ()
    sitemap_entries: tuple[SitemapEntry, ...] = ()


class DraftContentBrief(Skill[DraftBriefInputs, ContentBrief]):
    name = "draft_content_brief"
    model = "claude-sonnet-4-6"
    output_type = ContentBrief
    max_output_tokens = 6144
    streams = True  # progress_callback emits partial-JSON char counts as the brief builds

    def build_user_message(self, inputs: DraftBriefInputs) -> str:
        icp_json = inputs.icp_segment.model_dump_json(indent=2)
        serp_block = (
            "(no SERP analysis available — proceed from ICP + query alone)"
            if inputs.serp_analysis is None
            else f"```json\n{inputs.serp_analysis.model_dump_json(indent=2)}\n```"
        )
        past_block = (
            "(no similar past briefs)"
            if not inputs.similar_past_briefs
            else "\n".join(
                f"- (similarity {b.distance:.3f}) market={b.market!r}, angle={b.angle!r}"
                for b in inputs.similar_past_briefs
            )
        )
        sitemap_block = (
            "(no sitemap provided — internal_linking_suggestions should be left empty)"
            if not inputs.sitemap_entries
            else "Site URLs to consider for internal_linking_suggestions (pick 3-5 that "
            "*genuinely* support the brief, ignore irrelevant ones):\n"
            + "\n".join(
                f"  - {e.url}  (hint: {e.title_hint})"
                # Cap injected URLs at 80 so the prompt stays reasonable; the
                # sitemap parser already caps at 500 by default.
                for e in inputs.sitemap_entries[:80]
            )
        )
        return (
            f"Market: {inputs.market}\n"
            f"Target query: {inputs.target_query}\n\n"
            f"Priority ICP segment:\n```json\n{icp_json}\n```\n\n"
            f"SERP analysis:\n{serp_block}\n\n"
            f"Similar past briefs (do NOT repeat their angles — differentiate):\n{past_block}\n\n"
            f"{sitemap_block}\n\n"
            "Produce the ContentBrief per the system instructions."
        )

    def make_evaluators(self) -> list[Evaluator]:
        return [
            BriefStructure(),
            DraftAngleNonEmpty(),
            BriefSpecificityJudge(client=self.client, budget=self.budget),
        ]
