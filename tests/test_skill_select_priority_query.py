"""select_priority_query — strategic pick from scored journey."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import ICPSegment, Priority, ScoredQueryList
from guardrails import RunBudget
from skills.select_priority_query import SelectPriorityInputs, SelectPriorityQuery

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _icp() -> ICPSegment:
    return ICPSegment.model_validate(
        json.loads((CASSETTES / "define_icp.json").read_text())["input"]["segments"][0]
    )


def _scored() -> ScoredQueryList:
    return ScoredQueryList.model_validate(
        json.loads((CASSETTES / "score_queries.json").read_text())["input"]
    )


def test_returns_valid_priority(fake_client):
    fake_client.load_cassette("select_priority_query")
    skill = SelectPriorityQuery(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    result = skill.run(SelectPriorityInputs(scored=_scored(), icp_segment=_icp()))

    priority: Priority = result.output
    assert priority.selected_segment_label
    assert priority.selected_query.query.text
    assert priority.rationale
    # Rationale should mention runner-up reasoning, not just a score
    assert len(priority.rationale.split()) > 15


def test_priority_query_text_is_a_real_query_from_the_input(fake_client):
    fake_client.load_cassette("select_priority_query")
    skill = SelectPriorityQuery(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    scored = _scored()
    priority = skill.run(SelectPriorityInputs(scored=scored, icp_segment=_icp())).output

    input_texts = {s.query.text for s in scored.scored}
    assert priority.selected_query.query.text in input_texts
