"""Typer CLI entry point.

`geoquery brief --company X --market Y` runs the agent.
`geoquery runs` / `geoquery show <id>` query the episodic log.
Further subcommands (feedback, eval, eval-golden) land in later chunks.
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import typer

from agent import run_brief
from config import get_settings
from memory import EpisodicMemory

EVAL_REPORTS_DIR = "eval_reports"

app = typer.Typer(help="GEO Query → Content Brief Agent", no_args_is_help=True)


@app.command()
def brief(
    company: str = typer.Option(..., "--company", "-c", help="Target company name."),
    market: str = typer.Option(..., "--market", "-m", help="Target market description."),
    sitemap: str | None = typer.Option(
        None,
        "--sitemap",
        "-s",
        help="Optional sitemap URL. When provided, internal-linking suggestions "
        "in the brief are grounded in real URLs from your site.",
    ),
) -> None:
    """Generate a content brief end-to-end."""
    outcome = run_brief(
        company=company,
        market=market,
        sitemap_url=sitemap,
        on_progress=lambda msg: typer.echo(msg, err=True),
    )
    if outcome.status == "completed":
        typer.echo(f"run_id: {outcome.run_id}")
        typer.echo(f"brief:  {outcome.brief_path}")
        typer.echo(f"cost:   ${outcome.total_cost_usd:.4f}")
    else:
        typer.echo(f"run_id: {outcome.run_id}", err=True)
        typer.echo(f"status: {outcome.status}", err=True)
        typer.echo(f"cost:   ${outcome.total_cost_usd:.4f}", err=True)
        typer.echo(f"error:  {outcome.error}", err=True)
        raise typer.Exit(code=1)


@app.command()
def runs(limit: int = typer.Option(20, "--limit", "-n")) -> None:
    """List recent runs."""
    settings = get_settings()
    memory = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    for row in memory.list_runs(limit=limit):
        typer.echo(
            f"{row['id'][:8]}  {row['started_at']}  {row['status']:<15}  "
            f"${row['total_cost_usd']:.4f}  {row['company']}"
        )


@app.command()
def show(run_id: str = typer.Argument(...)) -> None:
    """Print a past run's metadata + skill invocations."""
    settings = get_settings()
    memory = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    run_row = memory.get_run(run_id)
    if run_row is None:
        typer.echo(f"run not found: {run_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(run_row, indent=2))
    typer.echo("\nskill invocations:")
    for inv in memory.get_invocations(run_id):
        typer.echo(
            f"  {inv['skill_name']:<25}  attempt={inv['attempt']}  "
            f"model={inv['model']}  cost=${inv['cost_usd']:.4f}  "
            f"duration={inv['duration_ms']}ms"
        )


@app.command()
def feedback(
    run_id: str = typer.Argument(..., help="Run ID returned by `geoquery brief`."),
    edited: Path = typer.Option(  # noqa: B008 — Typer idiom
        ..., "--edited", help="Path to the edited brief markdown file."
    ),
) -> None:
    """Capture human edits to a past brief and re-embed the preferred angle.

    Async outer-loop feedback: never blocks the original `brief` run. Use this
    after you've edited the brief markdown to your taste.
    """
    from feedback import capture_feedback

    outcome = capture_feedback(run_id=run_id, edited_brief_path=edited)
    typer.echo(f"run_id:         {outcome.run_id}")
    typer.echo(f"captured:       {outcome.captured}")
    typer.echo(f"angle changed:  {outcome.angle_changed}")
    typer.echo(f"lines changed:  {outcome.diff_lines_changed}")
    if outcome.angle_changed:
        typer.echo(f"original angle: {outcome.original_angle}")
        typer.echo(f"new angle:      {outcome.edited_angle}")


@app.command(name="eval-golden")
def eval_golden(
    report: bool = typer.Option(
        False, "--report", help="Write an HTML report to eval_reports/<timestamp>.html."
    ),
) -> None:
    """Run the golden regression set with real LLM calls; emit pass rate."""
    from datetime import datetime
    from pathlib import Path

    from anthropic import Anthropic

    from evals.golden_set import render_html_report, run_golden_set

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    result = run_golden_set(run_brief=run_brief, client=client)

    typer.echo(f"inputs:    {len(result.results)}")
    typer.echo(f"pass rate: {result.pass_rate * 100:.0f}%")
    typer.echo(f"cost:      ${result.total_cost_usd:.4f}")
    for r in result.results:
        status = "PASS" if r.passed else "FAIL"
        typer.echo(f"  [{status}] {r.input_id}  cost=${r.run_cost_usd:.4f}  {r.company}")

    if report:
        reports_dir = Path(EVAL_REPORTS_DIR)
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = reports_dir / f"golden_{stamp}.html"
        path.write_text(render_html_report(result), encoding="utf-8")
        typer.echo(f"report:    {path}")

    raise typer.Exit(code=0 if result.pass_rate >= 0.8 else 1)


@app.command(name="predict-outcomes")
def predict_outcomes(
    limit: int = typer.Option(
        10, "--limit", "-n", help="Max runs to score this batch (Opus is expensive)."
    ),
    high_score: float = typer.Option(
        0.9,
        "--high-score",
        help="Also score un-sampled runs whose eval composite is at least this.",
    ),
) -> None:
    """Predict 30-day search outcomes for a sampled subset of past briefs (v3
    Mechanism 3). SIMULATED signal — not real ranking data; see SELF_IMPROVEMENT.md.
    """
    import json as _json

    from anthropic import Anthropic

    from contracts import ContentBrief
    from guardrails import RunBudget
    from skills.predict_outcome import PredictOutcome, PredictOutcomeInputs

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    episodic = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    budget = RunBudget(max_cost_usd=settings.max_cost_usd)
    skill = PredictOutcome(client=client, budget=budget)

    scored = 0
    for run in episodic.runs_pending_outcome_prediction():
        if scored >= limit:
            break
        # Score the sampled 10% plus any already-high-scoring run — the
        # candidates worth a second opinion. Skip the rest: Opus isn't free.
        eval_score = episodic.compute_run_eval_score(run["id"])
        if not run["sampled"] and eval_score < high_score:
            continue
        draft = next(
            (
                inv
                for inv in reversed(episodic.get_invocations(run["id"]))
                if inv["skill_name"] == "draft_content_brief" and inv["output_json"]
            ),
            None,
        )
        if draft is None:
            continue
        brief = ContentBrief.model_validate(_json.loads(draft["output_json"]))
        result = skill.run(PredictOutcomeInputs(brief=brief, market=run["market"]))
        episodic.record_outcome_prediction(
            run_id=run["id"],
            predicted_top10=result.output.predicted_top10,
            confidence=result.output.confidence,
            reasoning=result.output.reasoning,
            model=result.model,
        )
        scored += 1
        verdict = "top-10" if result.output.predicted_top10 else "not top-10"
        typer.echo(f"  {run['company']}: {verdict} (confidence {result.output.confidence:.2f})")

    typer.echo(f"scored {scored} run(s); cost ${budget.spent_usd:.4f}")


@app.command(name="extract-patterns")
def extract_patterns(
    top_n: int = typer.Option(
        10, "--top-n", "-n", help="How many of the highest-scoring briefs to analyze."
    ),
) -> None:
    """Distill structural patterns from the highest-scoring past briefs (v3
    Mechanism 2). Run periodically — the drafter injects the latest result."""
    from anthropic import Anthropic

    from evals.winning_patterns import extract_winning_patterns
    from guardrails import RunBudget
    from memory import SemanticMemory

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    episodic = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    semantic = SemanticMemory(db_path=settings.data_dir / "semantic.db")
    budget = RunBudget(max_cost_usd=settings.max_cost_usd)

    patterns = extract_winning_patterns(
        semantic=semantic, episodic=episodic, client=client, budget=budget, top_n=top_n
    )
    if not patterns:
        typer.echo("no scored briefs yet — nothing to extract.")
        return
    typer.echo(f"extracted {len(patterns)} winning patterns (cost ${budget.spent_usd:.4f}):")
    for p in patterns:
        typer.echo(f"  - {p}")


if __name__ == "__main__":
    app()
