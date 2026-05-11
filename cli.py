"""Typer CLI entry point.

`geoquery brief --company X --market Y` runs the agent.
`geoquery runs` / `geoquery show <id>` query the episodic log.
Further subcommands (feedback, eval, eval-golden) land in later chunks.
"""

from __future__ import annotations

import json

import typer

from agent import run_brief
from config import get_settings
from memory import EpisodicMemory

app = typer.Typer(help="GEO Query → Content Brief Agent", no_args_is_help=True)


@app.command()
def brief(
    company: str = typer.Option(..., "--company", "-c", help="Target company name."),
    market: str = typer.Option(..., "--market", "-m", help="Target market description."),
) -> None:
    """Generate a content brief end-to-end."""
    outcome = run_brief(company=company, market=market)
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


if __name__ == "__main__":
    app()
