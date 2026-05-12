"""Agent orchestrator — wires the skills end-to-end.

Pipeline (chunks 1-4): define_icp -> generate_geo_query_list -> score_queries ->
select_priority_query -> tools.web_search -> analyze_serp -> draft_content_brief.
Chunk 5 replaces the placeholder drafter with a real SERP-informed version.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from config import Settings, get_settings
from contracts import ContentBrief, ICPSegmentList, Priority
from guardrails import BudgetExceeded, RetryExceeded, RunBudget
from memory import EpisodicMemory, SemanticMemory, SkillInvocationRecord
from memory.episodic import _now, serialize_for_log
from memory.semantic import Embedder
from skills.analyze_serp import AnalyzeSerp, AnalyzeSerpInputs
from skills.define_icp import DefineIcp, DefineIcpInputs
from skills.draft_content_brief import DraftBriefInputs, DraftContentBrief
from skills.generate_geo_query_list import GenerateGeoQueryList, GenerateQueriesInputs
from skills.research_company import ResearchCompany, ResearchCompanyInputs
from skills.score_queries import ScoreQueries, ScoreQueriesInputs
from skills.select_priority_query import SelectPriorityInputs, SelectPriorityQuery
from tools.dataforseo import fetch_keyword_metrics
from tools.sitemap_parser import parse_sitemap
from tools.web_fetch import fetch_page as _default_fetch_page
from tools.web_search import search_top_n

PageFetcher = Callable[[str], str | None]
ProgressCallback = Callable[[str], None]
"""Called at each skill boundary with a status line. Optional; default no-op."""

_EPISODIC_DB_NAME = "episodic.db"
_SEMANTIC_DB_NAME = "semantic.db"


def _icp_summary(segment) -> str:
    """One-line ICP descriptor used as the semantic-memory indexing key."""
    return (
        f"{segment.segment_label} | {segment.persona.role_job_title} | "
        f"pains: {', '.join(segment.firmographic.strategic_pain_points[:3])}"
    )


@dataclass
class AgentOutcome:
    run_id: str
    status: str
    brief_path: Path | None
    total_cost_usd: float
    error: str | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "untitled"


def _format_brief_markdown(brief: ContentBrief, run_id: str, company: str, market: str) -> str:
    sections = "\n\n".join(
        f"### {s.heading}\n\n**Purpose:** {s.purpose}\n\n"
        + "\n".join(f"- {pt}" for pt in s.key_points)
        for s in brief.structure
    )
    internal_links = (
        "\n".join(
            f"- [{link.suggested_anchor}]({link.url}) — {link.placement_rationale}"
            for link in brief.internal_linking_suggestions
        )
        or "_(none — sitemap grounding lands in chunk 12)_"
    )
    key_points = "\n".join(f"- {kp}" for kp in brief.key_points)
    sources = "\n".join(f"- {src}" for src in brief.sources)
    return (
        f"# Content Brief — {brief.target_query}\n\n"
        f"_Run `{run_id}` · Company: {company} · Market: {market}_\n\n"
        f"**ICP segment:** {brief.icp_segment_label}\n\n"
        f"**Audience:** {brief.audience}\n\n"
        f"**Angle:** {brief.angle}\n\n"
        f"**Recommended length:** {brief.recommended_length_words} words\n\n"
        f"## Structure\n\n{sections}\n\n"
        f"## Key Points\n\n{key_points}\n\n"
        f"## Sources\n\n{sources}\n\n"
        f"## Internal Linking Suggestions\n\n{internal_links}\n"
    )


def _write_brief(brief: ContentBrief, run_id: str, company: str, market: str, dir_: Path) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    filename = f"{run_id[:8]}_{_slug(company)}_{_slug(brief.target_query)}.md"
    path = dir_ / filename
    path.write_text(
        _format_brief_markdown(brief, run_id, company, market),
        encoding="utf-8",
    )
    return path


def run_brief(
    company: str,
    market: str,
    *,
    sitemap_url: str | None = None,
    settings: Settings | None = None,
    client: Anthropic | None = None,
    embedder: Embedder | None = None,
    fetch_page: PageFetcher | None = None,
    on_progress: ProgressCallback | None = None,
) -> AgentOutcome:
    settings = settings or get_settings()
    client = client or Anthropic(api_key=settings.anthropic_api_key)
    fetch_page = fetch_page or _default_fetch_page
    on_progress = on_progress or (lambda _: None)

    memory = EpisodicMemory(db_path=settings.data_dir / _EPISODIC_DB_NAME)
    semantic = SemanticMemory(db_path=settings.data_dir / _SEMANTIC_DB_NAME, embedder=embedder)
    run = memory.start_run(company=company, market=market)
    budget = RunBudget(max_cost_usd=settings.max_cost_usd)

    try:
        # Skill 1: research_company — CASINO dossier upstream of define_icp.
        on_progress("→ research_company")
        research_skill = ResearchCompany(client=client, budget=budget)
        research_start = time.monotonic()
        research_started_at = _now()
        research_result = research_skill.run(ResearchCompanyInputs(company=company, market=market))
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=research_skill.name,
                attempt=research_result.attempt,
                model=research_result.model,
                input_json=serialize_for_log({"company": company, "market": market}),
                output_json=research_result.output.model_dump_json(),
                eval_passed=research_result.eval_passed,
                eval_details_json=serialize_for_log(research_result.eval_failures),
                input_tokens=research_result.input_tokens,
                output_tokens=research_result.output_tokens,
                cost_usd=research_result.cost_usd,
                duration_ms=int((time.monotonic() - research_start) * 1000),
                started_at=research_started_at,
            )
        )

        on_progress(
            f"  ✓ research_company  {research_result.cost_usd:.4f}$  attempt={research_result.attempt}"
        )

        # Skill 2: define_icp (now consumes the dossier).
        on_progress("→ define_icp")
        icp_skill = DefineIcp(client=client, budget=budget)
        icp_inputs = DefineIcpInputs(
            company=company, market=market, company_dossier=research_result.output
        )
        icp_start = time.monotonic()
        icp_started_at = _now()
        icp_result = icp_skill.run(icp_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=icp_skill.name,
                attempt=icp_result.attempt,
                model=icp_result.model,
                input_json=serialize_for_log({"company": company, "market": market}),
                output_json=icp_result.output.model_dump_json(),
                eval_passed=icp_result.eval_passed,
                eval_details_json=serialize_for_log(icp_result.eval_failures),
                input_tokens=icp_result.input_tokens,
                output_tokens=icp_result.output_tokens,
                cost_usd=icp_result.cost_usd,
                duration_ms=int((time.monotonic() - icp_start) * 1000),
                started_at=icp_started_at,
            )
        )

        on_progress(f"  ✓ define_icp  {icp_result.cost_usd:.4f}$  attempt={icp_result.attempt}")

        segments: ICPSegmentList = icp_result.output
        primary_segment = segments.segments[0]

        # Skill 2: generate_geo_query_list (Haiku)
        on_progress("→ generate_geo_query_list  (Haiku)")
        queries_skill = GenerateGeoQueryList(client=client, budget=budget)
        queries_inputs = GenerateQueriesInputs(icp_segment=primary_segment, market=market)
        queries_start = time.monotonic()
        queries_started_at = _now()
        queries_result = queries_skill.run(queries_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=queries_skill.name,
                attempt=queries_result.attempt,
                model=queries_result.model,
                input_json=serialize_for_log(
                    {"icp_segment_label": primary_segment.segment_label, "market": market}
                ),
                output_json=queries_result.output.model_dump_json(),
                eval_passed=queries_result.eval_passed,
                eval_details_json=serialize_for_log(queries_result.eval_failures),
                input_tokens=queries_result.input_tokens,
                output_tokens=queries_result.output_tokens,
                cost_usd=queries_result.cost_usd,
                duration_ms=int((time.monotonic() - queries_start) * 1000),
                started_at=queries_started_at,
            )
        )
        on_progress(f"  ✓ generate_geo_query_list  {queries_result.cost_usd:.4f}$")
        journey = queries_result.output

        # Tool (chunk 11, hybrid): DataForSEO keyword metrics. Returns {} when
        # credentials are unset; score_queries falls back to LLM estimation.
        if settings.dataforseo_login:
            on_progress("→ dataforseo (real metrics)")
        keyword_metrics = fetch_keyword_metrics(
            login=settings.dataforseo_login,
            password=settings.dataforseo_password,
            queries=[q.text for q in journey.queries],
            budget=budget,
        )

        if settings.dataforseo_login:
            on_progress(
                f"  ✓ dataforseo  {len(keyword_metrics)}/{len(journey.queries)} queries hit"
            )

        # Skill 3: score_queries
        on_progress("→ score_queries")
        score_skill = ScoreQueries(client=client, budget=budget)
        score_inputs = ScoreQueriesInputs(
            journey=journey, icp_segment=primary_segment, keyword_metrics=keyword_metrics or None
        )
        score_start = time.monotonic()
        score_started_at = _now()
        score_result = score_skill.run(score_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=score_skill.name,
                attempt=score_result.attempt,
                model=score_result.model,
                input_json=serialize_for_log(
                    {"journey_size": len(journey.queries), "segment": primary_segment.segment_label}
                ),
                output_json=score_result.output.model_dump_json(),
                eval_passed=score_result.eval_passed,
                eval_details_json=serialize_for_log(score_result.eval_failures),
                input_tokens=score_result.input_tokens,
                output_tokens=score_result.output_tokens,
                cost_usd=score_result.cost_usd,
                duration_ms=int((time.monotonic() - score_start) * 1000),
                started_at=score_started_at,
            )
        )

        on_progress(f"  ✓ score_queries  {score_result.cost_usd:.4f}$")

        # Skill 4: select_priority_query
        on_progress("→ select_priority_query")
        priority_skill = SelectPriorityQuery(client=client, budget=budget)
        priority_inputs = SelectPriorityInputs(
            scored=score_result.output, icp_segment=primary_segment
        )
        priority_start = time.monotonic()
        priority_started_at = _now()
        priority_result = priority_skill.run(priority_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=priority_skill.name,
                attempt=priority_result.attempt,
                model=priority_result.model,
                input_json=serialize_for_log({"scored_count": len(score_result.output.scored)}),
                output_json=priority_result.output.model_dump_json(),
                eval_passed=priority_result.eval_passed,
                eval_details_json=serialize_for_log(priority_result.eval_failures),
                input_tokens=priority_result.input_tokens,
                output_tokens=priority_result.output_tokens,
                cost_usd=priority_result.cost_usd,
                duration_ms=int((time.monotonic() - priority_start) * 1000),
                started_at=priority_started_at,
            )
        )
        on_progress(f"  ✓ select_priority_query  {priority_result.cost_usd:.4f}$")
        priority: Priority = priority_result.output
        on_progress(f"    picked: {priority.selected_query.query.text!r}")

        # Tool: web_search — fetches top SERP results for the priority query.
        on_progress("→ web_search + web_fetch (top-3 pages)")
        serp_results = search_top_n(
            client=client, budget=budget, query=priority.selected_query.query.text, n=10
        )
        # Tool: web_fetch (chunk 10) — populate extracted_content on the top-3
        # results. SSRF-hardened, returns None on any failure (we degrade
        # gracefully — analyze_serp can still synthesize from snippets alone).
        for r in serp_results[:3]:
            r.extracted_content = fetch_page(r.url)

        fetched = sum(1 for r in serp_results[:3] if r.extracted_content)
        on_progress(f"  ✓ fetched {fetched}/3 pages, {len(serp_results)} results total")

        # Skill 5: analyze_serp — synthesizes common angles + content gaps.
        on_progress("→ analyze_serp")
        analyze_skill = AnalyzeSerp(client=client, budget=budget)
        analyze_inputs = AnalyzeSerpInputs(
            query_text=priority.selected_query.query.text,
            serp_results=serp_results,
        )
        analyze_start = time.monotonic()
        analyze_started_at = _now()
        analyze_result = analyze_skill.run(analyze_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=analyze_skill.name,
                attempt=analyze_result.attempt,
                model=analyze_result.model,
                input_json=serialize_for_log(
                    {
                        "query_text": priority.selected_query.query.text,
                        "serp_result_count": len(serp_results),
                    }
                ),
                output_json=analyze_result.output.model_dump_json(),
                eval_passed=analyze_result.eval_passed,
                eval_details_json=serialize_for_log(analyze_result.eval_failures),
                input_tokens=analyze_result.input_tokens,
                output_tokens=analyze_result.output_tokens,
                cost_usd=analyze_result.cost_usd,
                duration_ms=int((time.monotonic() - analyze_start) * 1000),
                started_at=analyze_started_at,
            )
        )

        # Semantic-memory RAG: retrieve top-3 similar past briefs.
        icp_sig = _icp_summary(primary_segment)
        similar = tuple(
            semantic.find_similar(
                market=market,
                icp_summary=icp_sig,
                angle_hint=priority.selected_query.query.text,
                k=3,
            )
        )

        on_progress(f"  ✓ analyze_serp  {analyze_result.cost_usd:.4f}$")

        # Tool (chunk 12): sitemap-grounded internal linking. Empty tuple when
        # no --sitemap was supplied; the drafter then leaves the section blank.
        sitemap_entries = tuple(parse_sitemap(sitemap_url)) if sitemap_url else ()
        if sitemap_url:
            on_progress(f"  ✓ sitemap parsed: {len(sitemap_entries)} URLs available")

        # Skill 6: draft_content_brief — SERP-informed + RAG-injected + sitemap.
        on_progress(f"→ draft_content_brief  (streaming, similar={len(similar)})")
        draft_skill = DraftContentBrief(client=client, budget=budget)
        draft_skill.progress_callback = lambda chars: on_progress(f"    ...streamed {chars} chars")
        draft_inputs = DraftBriefInputs(
            target_query=priority.selected_query.query.text,
            icp_segment=primary_segment,
            market=market,
            serp_analysis=analyze_result.output,
            similar_past_briefs=similar,
            sitemap_entries=sitemap_entries,
            company_dossier=research_result.output,
            priority=priority,
        )
        draft_start = time.monotonic()
        draft_started_at = _now()
        draft_result = draft_skill.run(draft_inputs)
        memory.log_skill_invocation(
            SkillInvocationRecord(
                run_id=run.id,
                skill_name=draft_skill.name,
                attempt=draft_result.attempt,
                model=draft_result.model,
                input_json=serialize_for_log(
                    {
                        "target_query": priority.selected_query.query.text,
                        "icp_segment_label": primary_segment.segment_label,
                        "market": market,
                    }
                ),
                output_json=draft_result.output.model_dump_json(),
                eval_passed=draft_result.eval_passed,
                eval_details_json=serialize_for_log(draft_result.eval_failures),
                input_tokens=draft_result.input_tokens,
                output_tokens=draft_result.output_tokens,
                cost_usd=draft_result.cost_usd,
                duration_ms=int((time.monotonic() - draft_start) * 1000),
                started_at=draft_started_at,
            )
        )

        on_progress(f"  ✓ draft_content_brief  {draft_result.cost_usd:.4f}$")

        brief_path = _write_brief(draft_result.output, run.id, company, market, settings.output_dir)
        # Index this run's brief into semantic memory for future RAG retrieval.
        semantic.index_brief(
            run_id=run.id,
            market=market,
            icp_summary=icp_sig,
            angle=draft_result.output.angle,
            brief_path=str(brief_path),
        )
        memory.finish_run(
            run_id=run.id,
            status="completed",
            total_cost_usd=budget.spent_usd,
            brief_path=str(brief_path),
        )
        # v2 chunk 7: probabilistically flag this run for human review.
        # No-op when sample_rate=0; raising the rate gates more runs into the
        # dashboard's Review_Queue page for judge-calibration feedback.
        from evals.production import maybe_sample_for_review

        if maybe_sample_for_review(memory, run.id, rate=settings.sample_rate):
            on_progress("  ✓ sampled for human review")
        return AgentOutcome(
            run_id=run.id,
            status="completed",
            brief_path=brief_path,
            total_cost_usd=budget.spent_usd,
        )

    except BudgetExceeded as e:
        memory.finish_run(run.id, "aborted_cost", budget.spent_usd, None)
        return AgentOutcome(run.id, "aborted_cost", None, budget.spent_usd, str(e))
    except RetryExceeded as e:
        memory.finish_run(run.id, "aborted_retries", budget.spent_usd, None)
        return AgentOutcome(run.id, "aborted_retries", None, budget.spent_usd, str(e))
    except Exception as e:
        memory.finish_run(run.id, "failed", budget.spent_usd, None)
        return AgentOutcome(run.id, "failed", None, budget.spent_usd, str(e))
