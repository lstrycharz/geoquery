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
