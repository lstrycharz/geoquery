"""BriefActionabilityJudge — are the brief's key_points concrete enough for a
writer to act on, or are they fluffy / abstract?
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ContentBrief
from evals.model_graded import BriefActionabilityJudge
from guardrails import RunBudget

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _load_brief() -> ContentBrief:
    return ContentBrief.model_validate(
        json.loads((CASSETTES / "draft_content_brief.json").read_text())["input"]
    )


def test_actionability_judge_passes_on_concrete_cassette(fake_client):
    fake_client.set_cassette(
        "judge_brief_actionability",
        {"input_tokens": 1300, "output_tokens": 40, "input": {"passed": True, "failures": []}},
    )
    judge = BriefActionabilityJudge(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = judge.evaluate(_load_brief())
    assert result.passed


def test_actionability_judge_fails_when_cassette_says_fail(fake_client):
    fake_client.set_cassette(
        "judge_brief_actionability",
        {
            "input_tokens": 1300,
            "output_tokens": 80,
            "input": {
                "passed": False,
                "failures": [
                    "section 2 key_points are abstract ('consider tooling') — writer can't draft from this"
                ],
            },
        },
    )
    judge = BriefActionabilityJudge(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = judge.evaluate(_load_brief())
    assert not result.passed
    assert any("abstract" in f for f in result.failures)


def test_actionability_judge_is_advisory_not_blocking():
    assert BriefActionabilityJudge.__dataclass_fields__["blocking"].default is False
