"""All Pydantic data contracts for the GEO Query agent.

Top-level outputs carry `schema_version` so old episodic-log rows stay parseable.
Nested models inherit their parent's version.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Company Dossier (research_company skill, added in chunk 9)
# ---------------------------------------------------------------------------


class CompanyDossier(BaseModel):
    schema_version: int = 1
    customer_segments: list[str]
    product_portfolio: list[str]
    inferred_icp: str
    icp_priorities: list[str]
    competitors: list[str]
    company_advantages: list[str]
    competitor_advantages: list[str]
    swot: dict[str, list[str]]
    porter_five_forces: dict[str, str]
    strategic_recommendations: list[str]
    executable_work_plan: list[str]


# ---------------------------------------------------------------------------
# ICP (define_icp skill)
# ---------------------------------------------------------------------------


class FirmographicDimensions(BaseModel):
    industry_vertical: str
    company_size: str
    geography: str
    organizational_structure: str
    buying_stage: str
    strategic_pain_points: list[str]
    trigger_events: list[str]


class PersonaDimensions(BaseModel):
    role_job_title: str
    demographic_context: str
    motivations: list[str]
    decision_criteria: list[str]
    language_patterns: list[str]
    frustrations: list[str]
    downstream_use_cases: list[str]
    information_sources: list[str]


class ICPSegment(BaseModel):
    schema_version: int = 1
    segment_label: str
    firmographic: FirmographicDimensions
    persona: PersonaDimensions


class ICPSegmentList(BaseModel):
    """Wrapper so the Anthropic structured-output schema is a single object,
    not a top-level array (the API requires the root to be an object)."""

    schema_version: int = 1
    segments: list[ICPSegment] = Field(min_length=2, max_length=4)


# ---------------------------------------------------------------------------
# GEO query list (generate_geo_query_list skill, added in chunk 2)
# ---------------------------------------------------------------------------


QueryFraming = Literal[
    "novice", "power-user", "vendor-comparing", "price-driven", "problem-aware"
]


class Query(BaseModel):
    position: int = Field(ge=1, le=28)
    text: str
    framing: QueryFraming
    refinement_applied: bool


class BuyerJourney(BaseModel):
    schema_version: int = 1
    queries: list[Query] = Field(min_length=22, max_length=28)
    journey_arc_summary: str

    @field_validator("queries")
    @classmethod
    def positions_must_be_unique_and_sequential(cls, v: list[Query]) -> list[Query]:
        positions = [q.position for q in v]
        if positions != list(range(1, len(v) + 1)):
            raise ValueError("queries must be numbered 1..N sequentially")
        return v


# ---------------------------------------------------------------------------
# Scoring (score_queries skill, added in chunk 3)
# ---------------------------------------------------------------------------


class KeywordMetrics(BaseModel):
    volume: int | None = None
    kd: float | None = None
    cpc: float | None = None
    serp_features: list[str] = Field(default_factory=list)


class ScoredQuery(BaseModel):
    schema_version: int = 1
    query: Query
    metrics: KeywordMetrics
    traffic_score: int = Field(ge=1, le=10)
    difficulty_score: int = Field(ge=1, le=10)
    business_value_score: int = Field(ge=1, le=10)
    composite: float
    competitor_urls: list[str] = Field(default_factory=list)
    rationale: str


class ScoredQueryList(BaseModel):
    schema_version: int = 1
    scored: list[ScoredQuery]


# ---------------------------------------------------------------------------
# Priority (select_priority_query skill, added in chunk 3)
# ---------------------------------------------------------------------------


class Priority(BaseModel):
    schema_version: int = 1
    selected_segment_label: str
    selected_query: ScoredQuery
    rationale: str


# ---------------------------------------------------------------------------
# SERP analysis (analyze_serp skill, added in chunk 4)
# ---------------------------------------------------------------------------


class SerpResult(BaseModel):
    rank: int
    url: str
    title: str
    snippet: str
    extracted_content: str | None = None


class SerpAnalysis(BaseModel):
    schema_version: int = 1
    query_text: str
    top_results: list[SerpResult]
    common_angles: list[str]
    content_gaps: list[str]
    recommended_format: str


# ---------------------------------------------------------------------------
# Content brief (draft_content_brief skill)
# ---------------------------------------------------------------------------


class InternalLink(BaseModel):
    url: str
    suggested_anchor: str
    placement_rationale: str


class BriefSection(BaseModel):
    heading: str
    purpose: str
    key_points: list[str]


class ContentBrief(BaseModel):
    schema_version: int = 1
    target_query: str
    icp_segment_label: str
    angle: str
    audience: str
    structure: list[BriefSection]
    key_points: list[str]
    sources: list[str]
    recommended_length_words: int
    internal_linking_suggestions: list[InternalLink] = Field(default_factory=list)
