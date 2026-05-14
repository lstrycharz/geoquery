"""predict_outcome — the Opus 30-day outcome judge (simulated signal)."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ContentBrief, OutcomePrediction
from guardrails import RunBudget
from skills.predict_outcome import PredictOutcome, PredictOutcomeInputs

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _brief() -> ContentBrief:
    payload = json.loads((CASSETTES / "draft_content_brief.json").read_text())["input"]
    return ContentBrief.model_validate(payload)


def test_predict_outcome_returns_a_structured_prediction(fake_client):
    fake_client.load_cassette("predict_outcome")
    skill = PredictOutcome(client=fake_client, budget=RunBudget(max_cost_usd=5.0))

    result = skill.run(PredictOutcomeInputs(brief=_brief(), market="B2B SaaS knowledge management"))

    assert isinstance(result.output, OutcomePrediction)
    assert isinstance(result.output.predicted_top10, bool)
    assert 0.0 <= result.output.confidence <= 1.0
    assert result.output.reasoning
    assert result.model == "claude-opus-4-7"
    assert result.cost_usd > 0


def test_predict_outcome_includes_the_brief_in_the_prompt(fake_client):
    skill = PredictOutcome(client=fake_client, budget=RunBudget(max_cost_usd=5.0))
    brief = _brief()
    message = skill.build_user_message(
        PredictOutcomeInputs(brief=brief, market="B2B SaaS knowledge management")
    )
    assert brief.angle in message
    assert "B2B SaaS knowledge management" in message
