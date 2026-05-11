"""Deterministic evaluators — pure-function tests, no LLM."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import (
    BuyerJourney,
    ContentBrief,
    ICPSegmentList,
    Query,
    ScoredQueryList,
    SerpAnalysis,
)
from evals.deterministic import (
    AnalyzeSerpStructure,
    BriefStructure,
    DraftAngleNonEmpty,
    IcpSegmentsInRange,
    PersonasHaveLanguagePatterns,
    QueryCountInRange,
    RefinementMatchesPositions,
    ScoredQueriesHaveValidComposites,
)

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"


def _load(name: str) -> dict:
    return json.loads((CASSETTES / f"{name}.json").read_text())["input"]


# --- ICP ---


def test_icp_segments_in_range_passes_on_good_cassette():
    out = ICPSegmentList.model_validate(_load("define_icp"))
    assert IcpSegmentsInRange().evaluate(out).passed


def test_personas_have_language_patterns_passes_on_good_cassette():
    out = ICPSegmentList.model_validate(_load("define_icp"))
    assert PersonasHaveLanguagePatterns().evaluate(out).passed


def test_personas_have_language_patterns_fails_when_empty():
    payload = _load("define_icp")
    payload["segments"][0]["persona"]["language_patterns"] = []
    out = ICPSegmentList.model_validate(payload)
    result = PersonasHaveLanguagePatterns().evaluate(out)
    assert not result.passed
    assert any("language_patterns" in f for f in result.failures)


# --- BuyerJourney ---


def test_query_count_passes_on_25():
    out = BuyerJourney.model_validate(_load("generate_geo_query_list"))
    assert QueryCountInRange().evaluate(out).passed


def test_refinement_matches_positions_passes_on_good_cassette():
    out = BuyerJourney.model_validate(_load("generate_geo_query_list"))
    assert RefinementMatchesPositions().evaluate(out).passed


def test_refinement_matches_positions_fails_when_broken():
    # Build a 22-query journey with a violation at position 5
    queries = [
        Query(
            position=i,
            text=f"q{i}",
            framing="novice",
            refinement_applied=(i >= 15 or i == 5),
        )
        for i in range(1, 23)
    ]
    journey = BuyerJourney(queries=queries, journey_arc_summary="…")
    result = RefinementMatchesPositions().evaluate(journey)
    assert not result.passed


# --- ScoredQueryList ---


def test_scored_queries_have_valid_composites_passes():
    out = ScoredQueryList.model_validate(_load("score_queries"))
    assert ScoredQueriesHaveValidComposites().evaluate(out).passed


# --- SerpAnalysis ---


def test_analyze_serp_structure_passes():
    out = SerpAnalysis.model_validate(_load("analyze_serp"))
    assert AnalyzeSerpStructure().evaluate(out).passed


def test_analyze_serp_structure_fails_when_gaps_missing():
    payload = _load("analyze_serp")
    payload["content_gaps"] = []
    out = SerpAnalysis.model_validate(payload)
    result = AnalyzeSerpStructure().evaluate(out)
    assert not result.passed


# --- ContentBrief ---


def test_brief_structure_passes():
    out = ContentBrief.model_validate(_load("draft_content_brief"))
    assert BriefStructure().evaluate(out).passed


def test_draft_angle_non_empty_passes():
    out = ContentBrief.model_validate(_load("draft_content_brief"))
    assert DraftAngleNonEmpty().evaluate(out).passed


def test_draft_angle_non_empty_fails_on_short_angle():
    payload = _load("draft_content_brief")
    payload["angle"] = "Two words"
    out = ContentBrief.model_validate(payload)
    assert not DraftAngleNonEmpty().evaluate(out).passed
