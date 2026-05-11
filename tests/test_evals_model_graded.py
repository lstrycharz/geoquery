"""Model-graded judges — cassette-driven."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import BuyerJourney, ContentBrief
from evals.model_graded import BriefSpecificityJudge, BuyerRealismJudge
from guardrails import RunBudget

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def test_buyer_realism_judge_passes_on_good_cassette(fake_client):
    fake_client.load_cassette("judge_buyer_realism")
    journey = BuyerJourney.model_validate(
        json.loads((CASSETTES / "generate_geo_query_list.json").read_text())["input"]
    )
    judge = BuyerRealismJudge(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = judge.evaluate(journey)
    assert result.passed


def test_buyer_realism_judge_fails_when_cassette_says_fail(fake_client):
    fake_client.set_cassette(
        "judge_buyer_realism",
        {
            "input_tokens": 1000,
            "output_tokens": 50,
            "input": {
                "passed": False,
                "failures": ["position 14 reads too expert-toned"],
            },
        },
    )
    journey = BuyerJourney.model_validate(
        json.loads((CASSETTES / "generate_geo_query_list.json").read_text())["input"]
    )
    judge = BuyerRealismJudge(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = judge.evaluate(journey)
    assert not result.passed
    assert "position 14" in result.failures[0]


def test_brief_specificity_judge_passes(fake_client):
    fake_client.load_cassette("judge_brief_specificity")
    brief = ContentBrief.model_validate(
        json.loads((CASSETTES / "draft_content_brief.json").read_text())["input"]
    )
    judge = BriefSpecificityJudge(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = judge.evaluate(brief)
    assert result.passed
