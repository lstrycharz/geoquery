"""Public entry point for the meta-agent — `python -m meta.run [--dry-run]`.

Chunk 2 wires the read-only path end to end: analyze the episodic DB, propose
one change for the top-ranked pattern, and emit the proposal as Markdown.
Opening a real PR (non-dry-run) lands in chunk 4.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic

from guardrails import RunBudget
from meta.analyze import Pattern, analyze
from meta.propose import Proposal, propose

# The committed, anonymized demo DB — the meta-agent's default data source so
# `--dry-run` works on a fresh checkout with no local run history.
DEFAULT_DB_PATH = Path("data/episodic.demo.db")


def format_proposal_markdown(pattern: Pattern, proposal: Proposal) -> str:
    """Render a Proposal as the Markdown body of a (future) PR."""
    paths = "\n".join(f"- `{p}`" for p in proposal.edit_paths)
    return (
        f"# Meta-agent proposal — `{pattern.signal_id}`\n\n"
        f"## Detected pattern\n{pattern.summary}\n\n"
        f"- kind: `{pattern.kind}`\n"
        f"- severity: {pattern.severity:.2f}\n\n"
        f"## Hypothesis\n{proposal.hypothesis}\n\n"
        f"## Change type\n`{proposal.change_type}`\n\n"
        f"## Edit surface\n{paths}\n\n"
        f"## Predicted effect\n{proposal.predicted_effect}\n\n"
        f"## Proposed diff\n```diff\n{proposal.diff}\n```\n"
    )


def run_meta_agent(
    db_path: Path,
    *,
    client: Anthropic,
    budget: RunBudget,
    dry_run: bool = True,
    now: datetime | None = None,
) -> str | None:
    """Analyze → propose → render. Returns the proposal Markdown, or None when
    `analyze` finds no actionable pattern.

    `dry_run=False` (open a real PR) is not wired until chunk 4.
    """
    patterns = analyze(db_path, now=now)
    if not patterns:
        return None
    top = patterns[0]
    proposal = propose(top, client=client, budget=budget, db_path=db_path)
    markdown = format_proposal_markdown(top, proposal)
    if not dry_run:
        raise NotImplementedError("opening a PR is not wired until v3 chunk 4")
    return markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta.run", description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="emit the proposal Markdown to stdout instead of opening a PR",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"episodic DB to analyze (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args(argv)

    from config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    budget = RunBudget(max_cost_usd=settings.max_cost_usd)

    markdown = run_meta_agent(args.db, client=client, budget=budget, dry_run=args.dry_run)
    if markdown is None:
        print("meta-agent: no actionable pattern found — nothing to propose.")
        return 0
    print(markdown)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
