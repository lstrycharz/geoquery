"""Golden regression set — runs the full pipeline for each curated input,
LLM-judges the resulting brief against expected themes, aggregates pass rate.

Run with: `geoquery eval-golden [--report]`. The report flag writes a static
HTML page summarizing pass/fail per input plus per-skill cost.

This is the bridge from "the tests are green" to "the prompt changes I just
made don't degrade the brief on real inputs." It uses real LLM calls.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from anthropic import Anthropic
from pydantic import BaseModel, Field

from agent import AgentOutcome
from contracts import ContentBrief
from guardrails import RunBudget
from skills.base import estimate_cost

GOLDEN_INPUTS_PATH = Path(__file__).parent.parent / "tests" / "golden" / "inputs.json"

_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_JUDGE_MAX_TOKENS = 1024


class GoldenJudgeVerdict(BaseModel):
    icp_keywords_matched: list[str] = Field(default_factory=list)
    icp_keywords_missing: list[str] = Field(default_factory=list)
    angle_keywords_matched: list[str] = Field(default_factory=list)
    angle_keywords_missing: list[str] = Field(default_factory=list)
    overall_pass: bool
    notes: str = ""


@dataclass
class GoldenResult:
    input_id: str
    company: str
    market: str
    run_status: str
    run_cost_usd: float
    brief_path: str | None
    verdict: GoldenJudgeVerdict | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.run_status == "completed" and bool(self.verdict and self.verdict.overall_pass)


@dataclass
class GoldenReport:
    started_at: str
    ended_at: str
    total_cost_usd: float
    results: list[GoldenResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)


def load_golden_inputs(path: Path = GOLDEN_INPUTS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def judge_brief_against_themes(
    *,
    client: Anthropic,
    brief: ContentBrief,
    icp_segment_label: str,
    expected_themes: dict,
    budget: RunBudget,
) -> GoldenJudgeVerdict:
    """Single Haiku call: does the brief hit the expected themes?

    Themes are kept loose on purpose (keywords / phrases the model checks for
    presence or paraphrase). Strict exact-match would be too brittle.
    """
    budget.check_can_spend(estimate_cost(_JUDGE_MODEL, 1200, _JUDGE_MAX_TOKENS))

    system = (
        "You judge whether a content brief hits the expected themes specified "
        "by a curated golden test. For each expected keyword, decide whether "
        "it appears verbatim or as a clear paraphrase in either the brief's "
        "angle/audience/sections (for angle keywords) or in the ICP segment "
        "label (for ICP role keywords). Be lenient on phrasing; strict on "
        "topical relevance.\n\n"
        "Set overall_pass=True if at least 60% of angle_keywords AND at least "
        "60% of icp_role_keywords match; otherwise False. Add a 1-sentence "
        "note when overall_pass=False explaining the biggest miss."
    )
    user = (
        f"ICP segment label: {icp_segment_label}\n"
        f"Brief angle: {brief.angle}\n"
        f"Brief audience: {brief.audience}\n"
        f"Brief structure headings: {[s.heading for s in brief.structure]}\n\n"
        f"Expected ICP role keywords: {expected_themes.get('icp_role_keywords', [])}\n"
        f"Expected brief angle keywords: {expected_themes.get('brief_angle_keywords', [])}\n\n"
        "Decide and emit your verdict."
    )

    tool_name = "emit_golden_judge"
    response = client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=_JUDGE_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": tool_name,
                "description": "Emit the golden-judge verdict.",
                "input_schema": GoldenJudgeVerdict.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    cost = estimate_cost(_JUDGE_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    budget.record_spend(cost)
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return GoldenJudgeVerdict.model_validate(block.input)
    raise RuntimeError("golden judge did not emit a verdict")


# Type alias for the injectable run_brief signature used by the runner.
RunBriefCallable = Callable[..., AgentOutcome]


def run_golden_set(
    *,
    run_brief: RunBriefCallable,
    client: Anthropic,
    judge_brief: Callable[..., GoldenJudgeVerdict] = judge_brief_against_themes,
    inputs_path: Path = GOLDEN_INPUTS_PATH,
    output_dir: Path | None = None,
) -> GoldenReport:
    """Run every golden input through the full pipeline and judge each brief."""
    inputs = load_golden_inputs(inputs_path)
    judge_budget = RunBudget(max_cost_usd=10.0)  # cumulative across all judges
    report = GoldenReport(
        started_at=datetime.now(UTC).isoformat(),
        ended_at="",
        total_cost_usd=0.0,
    )

    for entry in inputs:
        outcome = run_brief(
            company=entry["company"],
            market=entry["market"],
            sitemap_url=entry.get("sitemap_url"),
        )
        result = GoldenResult(
            input_id=entry["id"],
            company=entry["company"],
            market=entry["market"],
            run_status=outcome.status,
            run_cost_usd=outcome.total_cost_usd,
            brief_path=str(outcome.brief_path) if outcome.brief_path else None,
            error=outcome.error,
        )
        report.total_cost_usd += outcome.total_cost_usd
        if outcome.status == "completed" and outcome.brief_path:
            try:
                # Load the just-written brief markdown and extract its angle.
                # We don't deserialize from markdown — instead we re-load from
                # the episodic log's output_json, which is the canonical record.
                brief = _load_brief_from_outcome(outcome)
                verdict = judge_brief(
                    client=client,
                    brief=brief,
                    icp_segment_label=brief.icp_segment_label,
                    expected_themes=entry["expected_themes"],
                    budget=judge_budget,
                )
                result.verdict = verdict
            except Exception as e:
                result.error = f"judge failed: {e}"
        report.results.append(result)
        report.total_cost_usd += judge_budget.spent_usd
        judge_budget = RunBudget(max_cost_usd=10.0)  # reset for next entry

    report.ended_at = datetime.now(UTC).isoformat()
    return report


def _load_brief_from_outcome(outcome: AgentOutcome) -> ContentBrief:
    """Re-load the ContentBrief from the episodic log's stored JSON."""
    from config import get_settings
    from memory import EpisodicMemory

    settings = get_settings()
    memory = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    rows = memory.get_invocations(outcome.run_id)
    for inv in rows:
        if inv["skill_name"] == "draft_content_brief" and inv["output_json"]:
            return ContentBrief.model_validate_json(inv["output_json"])
    raise RuntimeError(f"no draft_content_brief output found for run {outcome.run_id}")


# --- HTML report -------------------------------------------------------------


_REPORT_TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Golden Eval Report — {{ report.started_at }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 960px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { margin-bottom: 0.2em; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 2em; }
  .summary { background: #f4f6f8; padding: 1em 1.5em; border-radius: 6px; margin-bottom: 2em; }
  .summary .rate { font-size: 2em; font-weight: 600; }
  .pass { color: #1a7f37; }
  .fail { color: #b42318; }
  .result { border: 1px solid #ddd; border-radius: 6px; padding: 1em 1.5em; margin-bottom: 1em; }
  .result h2 { margin-top: 0; font-size: 1.1em; }
  .badge { display: inline-block; padding: 0.1em 0.6em; border-radius: 999px; font-size: 0.85em; font-weight: 500; }
  .badge.pass { background: #dafbe1; color: #1a7f37; }
  .badge.fail { background: #ffe9e9; color: #b42318; }
  .kv { font-size: 0.9em; }
  .kv td { padding: 0.15em 0.6em 0.15em 0; vertical-align: top; }
  .kv td:first-child { color: #666; }
  code { background: #f4f6f8; padding: 0 0.3em; border-radius: 3px; }
</style></head><body>
<h1>Golden Eval Report</h1>
<div class="meta">{{ report.started_at }} → {{ report.ended_at }}</div>
<div class="summary">
  <div class="rate {% if report.pass_rate >= 0.8 %}pass{% else %}fail{% endif %}">
    Pass rate: {{ "%.0f" | format(report.pass_rate * 100) }}%
  </div>
  <div>Inputs: {{ report.results | length }} · Total cost: ${{ "%.4f" | format(report.total_cost_usd) }}</div>
</div>
{% for r in report.results %}
<div class="result">
  <h2>
    {{ r.company }} — {{ r.market }}
    <span class="badge {{ 'pass' if r.passed else 'fail' }}">{{ 'PASS' if r.passed else 'FAIL' }}</span>
  </h2>
  <table class="kv">
    <tr><td>input id</td><td><code>{{ r.input_id }}</code></td></tr>
    <tr><td>status</td><td>{{ r.run_status }}</td></tr>
    <tr><td>cost</td><td>${{ "%.4f" | format(r.run_cost_usd) }}</td></tr>
    {% if r.brief_path %}<tr><td>brief</td><td><code>{{ r.brief_path }}</code></td></tr>{% endif %}
    {% if r.error %}<tr><td>error</td><td>{{ r.error }}</td></tr>{% endif %}
    {% if r.verdict %}
    <tr><td>icp keywords</td><td>
      {% for k in r.verdict.icp_keywords_matched %}<span class="badge pass">{{ k }}</span> {% endfor %}
      {% for k in r.verdict.icp_keywords_missing %}<span class="badge fail">{{ k }}</span> {% endfor %}
    </td></tr>
    <tr><td>angle keywords</td><td>
      {% for k in r.verdict.angle_keywords_matched %}<span class="badge pass">{{ k }}</span> {% endfor %}
      {% for k in r.verdict.angle_keywords_missing %}<span class="badge fail">{{ k }}</span> {% endfor %}
    </td></tr>
    {% if r.verdict.notes %}<tr><td>note</td><td>{{ r.verdict.notes }}</td></tr>{% endif %}
    {% endif %}
  </table>
</div>
{% endfor %}
</body></html>
"""


def render_html_report(report: GoldenReport) -> str:
    """Render the report to a single self-contained HTML page."""
    import jinja2

    template = jinja2.Environment(autoescape=True).from_string(_REPORT_TEMPLATE)
    return template.render(report=report)
