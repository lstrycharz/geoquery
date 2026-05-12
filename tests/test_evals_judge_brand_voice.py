"""BrandVoiceMatchJudge — Haiku judge that compares brief tone to dossier signals.

Cassette-driven, identical pattern to the existing two judges.
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts import CompanyDossier, ContentBrief
from evals.model_graded import BrandVoiceMatchJudge
from guardrails import RunBudget

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _load_brief() -> ContentBrief:
    return ContentBrief.model_validate(
        json.loads((CASSETTES / "draft_content_brief.json").read_text())["input"]
    )


def _load_dossier() -> CompanyDossier:
    return CompanyDossier.model_validate(
        json.loads((CASSETTES / "research_company.json").read_text())["input"]
    )


def test_brand_voice_judge_passes_on_aligned_cassette(fake_client):
    fake_client.set_cassette(
        "judge_brand_voice_match",
        {"input_tokens": 1200, "output_tokens": 40, "input": {"passed": True, "failures": []}},
    )
    judge = BrandVoiceMatchJudge(
        client=fake_client, budget=RunBudget(max_cost_usd=3.0), dossier=_load_dossier()
    )
    result = judge.evaluate(_load_brief())
    assert result.passed
    assert result.failures == []


def test_brand_voice_judge_fails_when_cassette_says_fail(fake_client):
    fake_client.set_cassette(
        "judge_brand_voice_match",
        {
            "input_tokens": 1200,
            "output_tokens": 80,
            "input": {
                "passed": False,
                "failures": ["angle reads corporate, brand voice is informal-engineer"],
            },
        },
    )
    judge = BrandVoiceMatchJudge(
        client=fake_client, budget=RunBudget(max_cost_usd=3.0), dossier=_load_dossier()
    )
    result = judge.evaluate(_load_brief())
    assert not result.passed
    assert any("corporate" in f for f in result.failures)


def test_brand_voice_judge_is_advisory_not_blocking():
    # Advisory like the other two judges — eval_passed gates on deterministic
    # checks only. Inspect the dataclass default directly without calling.
    judge = BrandVoiceMatchJudge.__dataclass_fields__["blocking"]
    assert judge.default is False
