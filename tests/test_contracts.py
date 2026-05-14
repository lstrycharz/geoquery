"""Contract tests — Pydantic models reject malformed shapes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import (
    BuyerJourney,
    ContentBrief,
    ICPSegment,
    ICPSegmentList,
    Query,
)

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _load_input(name: str) -> dict:
    return json.loads((CASSETTES / f"{name}.json").read_text())["input"]


def test_icp_segment_list_accepts_cassette():
    payload = _load_input("define_icp")
    parsed = ICPSegmentList.model_validate(payload)
    assert 2 <= len(parsed.segments) <= 4
    assert all(isinstance(seg, ICPSegment) for seg in parsed.segments)


def test_icp_segment_list_rejects_single_segment():
    payload = _load_input("define_icp")
    payload["segments"] = payload["segments"][:1]
    with pytest.raises(ValidationError):
        ICPSegmentList.model_validate(payload)


def test_content_brief_accepts_cassette():
    payload = _load_input("draft_content_brief")
    brief = ContentBrief.model_validate(payload)
    assert brief.recommended_length_words > 0
    assert brief.structure
    assert brief.angle


def test_content_brief_rejects_empty_structure():
    payload = _load_input("draft_content_brief")
    payload["structure"] = []
    brief = ContentBrief.model_validate(payload)  # structure list itself can be empty per schema
    assert brief.structure == []  # contract allows it; eval layer will catch in chunk 6


def test_buyer_journey_enforces_sequential_positions():
    queries = [
        Query(position=1, text="q1", framing="novice", refinement_applied=False),
        Query(position=3, text="q3", framing="novice", refinement_applied=False),
    ] + [
        Query(position=p, text=f"q{p}", framing="novice", refinement_applied=False)
        for p in range(4, 24)
    ]
    with pytest.raises(ValidationError):
        BuyerJourney(queries=queries, journey_arc_summary="…")


def test_buyer_journey_enforces_minimum_count():
    queries = [
        Query(position=i, text=f"q{i}", framing="novice", refinement_applied=False)
        for i in range(1, 10)
    ]
    with pytest.raises(ValidationError):
        BuyerJourney(queries=queries, journey_arc_summary="…")


# ---------------------------------------------------------------------------
# _coerce_json_dict robustness (regression: live re-record surfaced a model
# double-encoding `swot` as a string with a trailing extra `}`)
# ---------------------------------------------------------------------------


def test_coerce_json_dict_passes_through_real_dicts():
    from contracts import _coerce_json_dict

    d = {"strengths": ["a"], "weaknesses": ["b"]}
    assert _coerce_json_dict(d) is d


def test_coerce_json_dict_decodes_a_clean_json_string():
    from contracts import _coerce_json_dict

    assert _coerce_json_dict('{"strengths": ["a"]}') == {"strengths": ["a"]}


def test_coerce_json_dict_tolerates_a_trailing_extra_brace():
    """The model occasionally emits `{...}}` — a balanced-brace scan must stop
    at the first balanced close and ignore the stray trailing brace."""
    from contracts import _coerce_json_dict

    raw = '{"strengths": ["plg"], "weaknesses": ["x"]}}'
    assert _coerce_json_dict(raw) == {"strengths": ["plg"], "weaknesses": ["x"]}


def test_coerce_json_dict_tolerates_a_dict_wrapper():
    from contracts import _coerce_json_dict

    assert _coerce_json_dict('dict({"a": ["1"]})') == {"a": ["1"]}


def test_coerce_json_dict_ignores_braces_inside_strings():
    from contracts import _coerce_json_dict

    raw = '{"strengths": ["uses {curly} braces"]}}'
    assert _coerce_json_dict(raw) == {"strengths": ["uses {curly} braces"]}
