"""Agent orchestrator — wires the skills end-to-end.

Chunk 1: only define_icp → draft_content_brief (skip the middle skills; pick
the segment's first decision-criterion as the placeholder target query).
Subsequent chunks layer in generate_geo_query_list, score_queries,
select_priority_query, analyze_serp, and replace the placeholder drafter.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from config import Settings, get_settings
from contracts import ContentBrief, ICPSegment, ICPSegmentList
from guardrails import BudgetExceeded, RetryExceeded, RunBudget
from memory import EpisodicMemory, SkillInvocationRecord
from memory.episodic import _now, serialize_for_log
from skills.define_icp import DefineIcp, DefineIcpInputs
from skills.draft_content_brief import DraftBriefInputs, DraftContentBrief

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


def _placeholder_target_query(segment: ICPSegment, market: str) -> str:
    pain = (segment.firmographic.strategic_pain_points or ["the core problem"])[0]
    return f"how to solve {pain.lower()} in {market.lower()}"


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

        # Skill (placeholder): draft_content_brief
        target_query = _placeholder_target_query(primary_segment, market)
        draft_skill = DraftContentBrief(client=client, budget=budget)
        draft_inputs = DraftBriefInputs(
            target_query=target_query,
            icp_segment=primary_segment,
            market=market,
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
                        "target_query": target_query,
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
