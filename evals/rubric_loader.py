"""Rubric loader — judge prompts as first-class Markdown artifacts.

Mirrors `skills.base.load_prompt` for `skills/prompts/`. Lives in its own module
so tests can monkeypatch RUBRICS_DIR without touching the wider evals package.
"""

from __future__ import annotations

from pathlib import Path

RUBRICS_DIR = Path(__file__).parent / "rubrics"


def load_rubric(name: str, **substitutions: str) -> str:
    """Read evals/rubrics/<name>.md and substitute any {placeholder} keys.

    A missing placeholder raises KeyError rather than leaving a literal `{x}`
    in the rendered prompt — silent unfilled placeholders would corrupt the
    judge's instructions.
    """
    path = RUBRICS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"rubric not found: {path}")
    template = path.read_text(encoding="utf-8")
    # Always format: KeyError surfaces missing placeholders instead of leaving
    # `{x}` literals in the prompt. Rubric authors escape literal braces (e.g.
    # JSON examples) as `{{`/`}}` per Python str.format semantics.
    return template.format(**substitutions)
