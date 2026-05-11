"""generate_geo_query_list — Haiku, 5-framing single-prompt buyer journey."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from contracts import BuyerJourney, ICPSegment
from guardrails import RunBudget
from skills.generate_geo_query_list import GenerateGeoQueryList, GenerateQueriesInputs

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _icp_segment() -> ICPSegment:
    payload = json.loads((CASSETTES / "define_icp.json").read_text())["input"]
    return ICPSegment.model_validate(payload["segments"][0])


def test_skill_uses_haiku_per_source_skill_warning():
    assert GenerateGeoQueryList.model == "claude-haiku-4-5"


def test_returns_validated_journey(fake_client):
    fake_client.load_cassette("generate_geo_query_list")
    skill = GenerateGeoQueryList(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(
        GenerateQueriesInputs(icp_segment=_icp_segment(), market="B2B SaaS knowledge mgmt")
    )

    journey: BuyerJourney = result.output
    assert 22 <= len(journey.queries) <= 28
    assert journey.journey_arc_summary
    assert journey.queries[0].position == 1
    assert journey.queries[-1].position == len(journey.queries)


def test_cassette_has_five_queries_per_framing():
    payload = json.loads((CASSETTES / "generate_geo_query_list.json").read_text())["input"]
    counts = Counter(q["framing"] for q in payload["queries"])
    # Cassette models the desired output: 5 per framing, 25 total.
    assert counts == {
        "novice": 5,
        "problem-aware": 5,
        "power-user": 5,
        "vendor-comparing": 5,
        "price-driven": 5,
    }


def test_cassette_refinement_applies_only_to_positions_15_plus():
    payload = json.loads((CASSETTES / "generate_geo_query_list.json").read_text())["input"]
    for q in payload["queries"]:
        if q["position"] <= 14:
            assert q["refinement_applied"] is False, q
        else:
            assert q["refinement_applied"] is True, q
