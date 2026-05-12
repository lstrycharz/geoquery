"""SearchIntentAlignmentJudge — does the brief actually serve the priority
query's intent, or has the angle drifted into a different topic?
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ContentBrief, Priority
from evals.model_graded import SearchIntentAlignmentJudge
from guardrails import RunBudget

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _load_priority() -> Priority:
    return Priority.model_validate(
        json.loads((CASSETTES / "select_priority_query.json").read_text())["input"]
    )


def _load_brief() -> ContentBrief:
    return ContentBrief.model_validate(
        json.loads((CASSETTES / "draft_content_brief.json").read_text())["input"]
    )


def test_search_intent_judge_passes_on_aligned_cassette(fake_client):
    fake_client.set_cassette(
        "judge_search_intent_alignment",
        {"input_tokens": 1200, "output_tokens": 40, "input": {"passed": True, "failures": []}},
    )
    judge = SearchIntentAlignmentJudge(
        client=fake_client, budget=RunBudget(max_cost_usd=3.0), priority=_load_priority()
    )
    result = judge.evaluate(_load_brief())
    assert result.passed


def test_search_intent_judge_fails_when_cassette_says_fail(fake_client):
    fake_client.set_cassette(
        "judge_search_intent_alignment",
        {
            "input_tokens": 1200,
            "output_tokens": 80,
            "input": {
                "passed": False,
                "failures": [
                    "angle pivots to feature comparison, query is 'alternatives to' intent"
                ],
            },
        },
    )
    judge = SearchIntentAlignmentJudge(
        client=fake_client, budget=RunBudget(max_cost_usd=3.0), priority=_load_priority()
    )
    result = judge.evaluate(_load_brief())
    assert not result.passed
    assert any("alternatives" in f for f in result.failures)


def test_search_intent_judge_is_advisory_not_blocking():
    assert SearchIntentAlignmentJudge.__dataclass_fields__["blocking"].default is False
