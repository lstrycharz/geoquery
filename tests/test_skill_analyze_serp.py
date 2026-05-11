"""analyze_serp — synthesizes SerpAnalysis from a list of SerpResult."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import SerpAnalysis, SerpResult, SerpResultList
from guardrails import RunBudget
from skills.analyze_serp import AnalyzeSerp, AnalyzeSerpInputs

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _serp_results() -> list[SerpResult]:
    return SerpResultList.model_validate(
        json.loads((CASSETTES / "serp_results.json").read_text())["input"]
    ).results


def test_returns_serp_analysis(fake_client):
    fake_client.load_cassette("analyze_serp")
    skill = AnalyzeSerp(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(
        AnalyzeSerpInputs(
            query_text="alternatives to notion for engineering documentation",
            serp_results=_serp_results(),
        )
    )

    analysis: SerpAnalysis = result.output
    assert analysis.common_angles
    assert analysis.content_gaps
    assert analysis.recommended_format
    assert analysis.top_results
