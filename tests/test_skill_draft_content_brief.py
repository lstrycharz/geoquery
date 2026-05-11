"""draft_content_brief skill (placeholder) — cassette-driven validation."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ContentBrief, ICPSegment
from guardrails import RunBudget
from skills.draft_content_brief import DraftBriefInputs, DraftContentBrief

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _first_segment_from_icp_cassette() -> ICPSegment:
    payload = json.loads((CASSETTES / "define_icp.json").read_text())["input"]
    return ICPSegment.model_validate(payload["segments"][0])


def test_draft_brief_returns_validated_brief(fake_client):
    fake_client.load_cassette("draft_content_brief")
    segment = _first_segment_from_icp_cassette()
    skill = DraftContentBrief(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(
        DraftBriefInputs(
            target_query="how to pick a knowledge base",
            icp_segment=segment,
            market="B2B SaaS knowledge management",
        )
    )

    assert isinstance(result.output, ContentBrief)
    assert result.output.angle
    assert result.output.structure
    assert result.output.recommended_length_words > 0
    assert result.cost_usd > 0
