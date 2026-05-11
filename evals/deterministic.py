"""Deterministic evaluators — pure functions that return EvalResult.

These check shape and basic semantics that Pydantic alone can't enforce
(e.g. "language_patterns is non-empty per segment", "refinement_applied
applies to positions 15+ only").

The interface is intentionally tiny: every evaluator is a callable object
with `name` and `.evaluate(output) -> EvalResult`. Skill subclasses return
a list of these from `make_evaluators()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from contracts import (
    BuyerJourney,
    CompanyDossier,
    ContentBrief,
    ICPSegmentList,
    ScoredQueryList,
    SerpAnalysis,
)


@dataclass
class EvalResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)


@runtime_checkable
class Evaluator(Protocol):
    name: str
    # Blocking evaluators trigger the inner-loop revision when they fail.
    # Advisory evaluators surface their failures in the episodic log but
    # do not block the pipeline. Deterministic shape checks should block;
    # model-graded judgment calls are usually advisory.
    blocking: bool

    def evaluate(self, output: Any) -> EvalResult: ...


# --- research_company ---------------------------------------------------------


@dataclass
class CompanyDossierComplete:
    name: str = "company_dossier_complete"
    blocking: bool = True

    def evaluate(self, output: CompanyDossier) -> EvalResult:
        fails: list[str] = []
        if not output.customer_segments:
            fails.append("customer_segments is empty")
        if not output.product_portfolio:
            fails.append("product_portfolio is empty")
        if not output.inferred_icp.strip():
            fails.append("inferred_icp is empty")
        if not output.competitors:
            fails.append("competitors is empty")
        required_swot = {"strengths", "weaknesses", "opportunities", "threats"}
        missing_swot = required_swot - set(output.swot.keys())
        if missing_swot:
            fails.append(f"swot missing buckets: {sorted(missing_swot)}")
        required_forces = {
            "buyer_power",
            "supplier_power",
            "rivalry",
            "new_entrants",
            "substitutes",
        }
        missing_forces = required_forces - set(output.porter_five_forces.keys())
        if missing_forces:
            fails.append(f"porter_five_forces missing: {sorted(missing_forces)}")
        if not output.strategic_recommendations:
            fails.append("strategic_recommendations is empty")
        if not output.executable_work_plan:
            fails.append("executable_work_plan is empty")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


# --- define_icp ---------------------------------------------------------------


@dataclass
class IcpSegmentsInRange:
    name: str = "icp_segments_in_range"
    blocking: bool = True

    def evaluate(self, output: ICPSegmentList) -> EvalResult:
        fails: list[str] = []
        n = len(output.segments)
        if not (2 <= n <= 4):
            fails.append(f"need 2-4 segments, got {n}")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


@dataclass
class PersonasHaveLanguagePatterns:
    name: str = "personas_have_language_patterns"
    blocking: bool = True

    def evaluate(self, output: ICPSegmentList) -> EvalResult:
        fails: list[str] = []
        for i, seg in enumerate(output.segments):
            if not seg.persona.language_patterns:
                fails.append(f"segment[{i}] missing language_patterns")
            if not seg.persona.decision_criteria:
                fails.append(f"segment[{i}] missing decision_criteria")
            if not seg.firmographic.strategic_pain_points:
                fails.append(f"segment[{i}] missing strategic_pain_points")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


# --- generate_geo_query_list --------------------------------------------------


@dataclass
class QueryCountInRange:
    name: str = "query_count_in_range"
    blocking: bool = True

    def evaluate(self, output: BuyerJourney) -> EvalResult:
        fails: list[str] = []
        n = len(output.queries)
        if not (22 <= n <= 28):
            fails.append(f"need 22-28 queries, got {n}")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


@dataclass
class RefinementMatchesPositions:
    """Positions 1-14 are broad (refinement_applied=False); 15+ are refined."""

    name: str = "refinement_matches_positions"
    blocking: bool = True

    def evaluate(self, output: BuyerJourney) -> EvalResult:
        fails: list[str] = []
        for q in output.queries:
            if q.position <= 14 and q.refinement_applied:
                fails.append(f"position {q.position} is refined but should be broad")
            if q.position >= 15 and not q.refinement_applied:
                fails.append(f"position {q.position} is broad but should be refined")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


# --- score_queries ------------------------------------------------------------


@dataclass
class ScoredQueriesHaveValidComposites:
    name: str = "scored_queries_have_valid_composites"
    blocking: bool = True

    def evaluate(self, output: ScoredQueryList) -> EvalResult:
        fails: list[str] = []
        if not output.scored:
            fails.append("no scored queries")
        for s in output.scored:
            if not (1.0 <= s.composite <= 10.0):
                fails.append(f"position {s.query.position}: composite {s.composite} out of range")
            if not s.rationale.strip():
                fails.append(f"position {s.query.position}: empty rationale")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


# --- analyze_serp -------------------------------------------------------------


@dataclass
class AnalyzeSerpStructure:
    name: str = "analyze_serp_structure"
    blocking: bool = True

    def evaluate(self, output: SerpAnalysis) -> EvalResult:
        fails: list[str] = []
        if not output.common_angles:
            fails.append("common_angles is empty")
        if not output.content_gaps:
            fails.append("content_gaps is empty")
        if not output.recommended_format.strip():
            fails.append("recommended_format is empty")
        if not output.top_results:
            fails.append("top_results is empty")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


# --- draft_content_brief ------------------------------------------------------


@dataclass
class BriefStructure:
    name: str = "brief_structure"
    blocking: bool = True

    def evaluate(self, output: ContentBrief) -> EvalResult:
        fails: list[str] = []
        if not output.structure:
            fails.append("structure is empty")
        for i, sec in enumerate(output.structure):
            if not sec.heading.strip():
                fails.append(f"structure[{i}] has empty heading")
            if not sec.key_points:
                fails.append(f"structure[{i}] has empty key_points")
        if not output.key_points:
            fails.append("top-level key_points is empty")
        if not output.sources:
            fails.append("sources is empty")
        if output.recommended_length_words <= 0:
            fails.append("recommended_length_words is non-positive")
        return EvalResult(name=self.name, passed=not fails, failures=fails)


@dataclass
class DraftAngleNonEmpty:
    name: str = "draft_angle_non_empty"
    blocking: bool = True
    min_words: int = 6

    def evaluate(self, output: ContentBrief) -> EvalResult:
        fails: list[str] = []
        words = output.angle.split()
        if len(words) < self.min_words:
            fails.append(f"angle is too short ({len(words)} words); needs >= {self.min_words}")
        return EvalResult(name=self.name, passed=not fails, failures=fails)
