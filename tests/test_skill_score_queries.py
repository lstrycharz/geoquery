"""score_queries — scores every query; uses ICP context."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import BuyerJourney, ICPSegment, ScoredQueryList
from guardrails import RunBudget
from skills.score_queries import ScoreQueries, ScoreQueriesInputs

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _icp() -> ICPSegment:
    return ICPSegment.model_validate(
        json.loads((CASSETTES / "define_icp.json").read_text())["input"]["segments"][0]
    )


def _journey() -> BuyerJourney:
    return BuyerJourney.model_validate(
        json.loads((CASSETTES / "generate_geo_query_list.json").read_text())["input"]
    )


def test_returns_one_scored_query_per_input_query(fake_client):
    fake_client.load_cassette("score_queries")
    skill = ScoreQueries(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = skill.run(ScoreQueriesInputs(journey=_journey(), icp_segment=_icp()))

    scored: ScoredQueryList = result.output
    assert len(scored.scored) == 25
    assert all(1 <= s.traffic_score <= 10 for s in scored.scored)
    assert all(1 <= s.difficulty_score <= 10 for s in scored.scored)
    assert all(1 <= s.business_value_score <= 10 for s in scored.scored)
    # No DataForSEO data yet — metrics empty
    assert all(s.metrics.volume is None for s in scored.scored)
    assert all(s.competitor_urls == [] for s in scored.scored)


def test_composite_is_present_and_in_range(fake_client):
    fake_client.load_cassette("score_queries")
    skill = ScoreQueries(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    scored = skill.run(ScoreQueriesInputs(journey=_journey(), icp_segment=_icp())).output

    for s in scored.scored:
        assert 1.0 <= s.composite <= 10.0
