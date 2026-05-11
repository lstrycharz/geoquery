"""draft_content_brief — SERP-informed and SERP-less paths both work."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ContentBrief, ICPSegment, SerpAnalysis
from guardrails import RunBudget
from skills.draft_content_brief import DraftBriefInputs, DraftContentBrief

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _first_segment_from_icp_cassette() -> ICPSegment:
    payload = json.loads((CASSETTES / "define_icp.json").read_text())["input"]
    return ICPSegment.model_validate(payload["segments"][0])


def _serp_analysis() -> SerpAnalysis:
    return SerpAnalysis.model_validate(
        json.loads((CASSETTES / "analyze_serp.json").read_text())["input"]
    )


def test_draft_brief_with_serp_analysis(fake_client):
    fake_client.load_cassette("draft_content_brief")
    skill = DraftContentBrief(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(
        DraftBriefInputs(
            target_query="alternatives to notion for engineering documentation",
            icp_segment=_first_segment_from_icp_cassette(),
            market="B2B SaaS knowledge management",
            serp_analysis=_serp_analysis(),
        )
    )

    assert isinstance(result.output, ContentBrief)
    assert result.output.angle
    assert result.output.structure
    assert result.output.recommended_length_words > 0
    assert result.cost_usd > 0


def test_draft_brief_without_serp_analysis_still_works(fake_client):
    """Backward-compatible: callers pre-chunk-4 don't pass a SerpAnalysis."""
    fake_client.load_cassette("draft_content_brief")
    skill = DraftContentBrief(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(
        DraftBriefInputs(
            target_query="how to pick a knowledge base",
            icp_segment=_first_segment_from_icp_cassette(),
            market="B2B SaaS knowledge management",
            serp_analysis=None,
        )
    )

    assert isinstance(result.output, ContentBrief)
