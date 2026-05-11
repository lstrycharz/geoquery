"""Agent orchestrator — wires the skills end-to-end.

Pipeline (chunks 1-4): define_icp -> generate_geo_query_list -> score_queries ->
select_priority_query -> tools.web_search -> analyze_serp -> draft_content_brief.
Chunk 5 replaces the placeholder drafter with a real SERP-informed version.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from config import Settings, get_settings
from contracts import ContentBrief, ICPSegmentList, Priority
from guardrails import BudgetExceeded, RetryExceeded, RunBudget
from memory import EpisodicMemory, SkillInvocationRecord
from memory.episodic import _now, serialize_for_log
from skills.analyze_serp import AnalyzeSerp, AnalyzeSerpInputs
from skills.define_icp import DefineIcp, DefineIcpInputs
from skills.draft_content_brief import DraftBriefInputs, DraftContentBrief
from skills.generate_geo_query_list import GenerateGeoQueryList, GenerateQueriesInputs
from skills.score_queries import ScoreQueries, ScoreQueriesInputs
from skills.select_priority_query import SelectPriorityInputs, SelectPriorityQuery
from tools.web_search import search_top_n

_EPISODIC_DB_NAME = "episodic.db"


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
    settings: Settings | None = None,
    client: Anthropic | None = None,
) -> AgentOutcome:
    settings = settings or get_settings()
    client = client or Anthropic(api_key=settings.anthropic_api_key)

    memory = EpisodicMemory(db_path=settings.data_dir / _EPISODIC_DB_NAME)
    run = memory.start_run(company=company, market=market)
    budget = RunBudget(max_cost_usd=settings.max_cost_usd)

    try:
        # Skill 1: define_icp
        icp_skill = DefineIcp(client=client, budget=budget)
        icp_inputs = DefineIcpInputs(company=company, market=market)
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
                input_tokens=icp_result.input_tokens,
                output_tokens=icp_result.output_tokens,
                cost_usd=icp_result.cost_usd,
                duration_ms=int((time.monotonic() - icp_start) * 1000),
                started_at=icp_started_at,
            )
        )

        segments: ICPSegmentList = icp_result.output
        primary_segment = segments.segments[0]

        # Skill 2: generate_geo_query_list (Haiku)
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
                input_tokens=queries_result.input_tokens,
                output_tokens=queries_result.output_tokens,
                cost_usd=queries_result.cost_usd,
                duration_ms=int((time.monotonic() - queries_start) * 1000),
                started_at=queries_started_at,
            )
        )
        journey = queries_result.output

        # Skill 3: score_queries
        score_skill = ScoreQueries(client=client, budget=budget)
        score_inputs = ScoreQueriesInputs(journey=journey, icp_segment=primary_segment)
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
                input_tokens=score_result.input_tokens,
                output_tokens=score_result.output_tokens,
                cost_usd=score_result.cost_usd,
                duration_ms=int((time.monotonic() - score_start) * 1000),
                started_at=score_started_at,
            )
        )

        # Skill 4: select_priority_query
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
                input_tokens=priority_result.input_tokens,
                output_tokens=priority_result.output_tokens,
                cost_usd=priority_result.cost_usd,
                duration_ms=int((time.monotonic() - priority_start) * 1000),
                started_at=priority_started_at,
            )
        )
        priority: Priority = priority_result.output

        # Tool: web_search — fetches top SERP results for the priority query.
        serp_results = search_top_n(
            client=client, budget=budget, query=priority.selected_query.query.text, n=10
        )

        # Skill 5: analyze_serp — synthesizes common angles + content gaps.
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
                input_tokens=analyze_result.input_tokens,
                output_tokens=analyze_result.output_tokens,
                cost_usd=analyze_result.cost_usd,
                duration_ms=int((time.monotonic() - analyze_start) * 1000),
                started_at=analyze_started_at,
            )
        )

        # Skill 6: draft_content_brief — now SERP-informed (chunk 5).
        draft_skill = DraftContentBrief(client=client, budget=budget)
        draft_inputs = DraftBriefInputs(
            target_query=priority.selected_query.query.text,
            icp_segment=primary_segment,
            market=market,
            serp_analysis=analyze_result.output,
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
                input_tokens=draft_result.input_tokens,
                output_tokens=draft_result.output_tokens,
                cost_usd=draft_result.cost_usd,
                duration_ms=int((time.monotonic() - draft_start) * 1000),
                started_at=draft_started_at,
            )
        )

        brief_path = _write_brief(
            draft_result.output, run.id, company, market, settings.output_dir
        )
        memory.finish_run(
            run_id=run.id,
            status="completed",
            total_cost_usd=budget.spent_usd,
            brief_path=str(brief_path),
        )
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
