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
