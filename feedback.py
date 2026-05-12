"""Outer-loop feedback — capture human edits to a brief and re-embed the
preferred angle into semantic memory so future similar runs are nudged
toward it.

Invoked async via `geoquery feedback <run-id> --edited path/to/edited.md`.
Never blocks the original `geoquery brief` run.

Design:
- The user edits the brief markdown file in place (or saves a copy).
- They run this subcommand once they're satisfied with the edit.
- We diff the edited file against the original brief from the run; if the
  `**Angle:**` line changed materially, we re-embed the new angle into the
  semantic memory as a preferred-angle signal (using the same `index_brief`
  path the drafter retrieves from).
- The full diff summary is captured in the episodic `human_edits` table.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import Settings, get_settings
from memory import EpisodicMemory, SemanticMemory
from memory.semantic import Embedder

_ANGLE_LINE_RE = re.compile(r"^\*\*Angle:\*\*\s*(.+)$", re.MULTILINE)
_ICP_LINE_RE = re.compile(r"^\*\*ICP segment:\*\*\s*(.+)$", re.MULTILINE)


@dataclass
class FeedbackOutcome:
    run_id: str
    captured: bool  # True if a human_edit row was created
    angle_changed: bool  # True if the angle line differs
    original_angle: str
    edited_angle: str
    diff_lines_changed: int


def _extract(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def capture_feedback(
    *,
    run_id: str,
    edited_brief_path: Path,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
) -> FeedbackOutcome:
    settings = settings or get_settings()
    memory = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    semantic = SemanticMemory(db_path=settings.data_dir / "semantic.db", embedder=embedder)

    run = memory.get_run(run_id)
    if not run:
        raise FileNotFoundError(f"no run with id {run_id!r}")
    original_path = Path(run["brief_path"]) if run.get("brief_path") else None
    if not original_path or not original_path.is_file():
        raise FileNotFoundError(f"original brief missing for run {run_id!r}")
    if not edited_brief_path.is_file():
        raise FileNotFoundError(f"edited brief not found: {edited_brief_path}")

    original = original_path.read_text(encoding="utf-8")
    edited = edited_brief_path.read_text(encoding="utf-8")

    original_angle = _extract(_ANGLE_LINE_RE, original) or ""
    edited_angle = _extract(_ANGLE_LINE_RE, edited) or original_angle
    angle_changed = original_angle.strip() != edited_angle.strip()

    diff = list(
        difflib.unified_diff(
            original.splitlines(),
            edited.splitlines(),
            fromfile=str(original_path),
            tofile=str(edited_brief_path),
            lineterm="",
        )
    )
    diff_summary = "\n".join(diff[:200])  # cap for storage
    lines_changed = sum(
        1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )

    memory.log_human_edit(
        run_id=run_id,
        original_brief_path=str(original_path),
        edited_brief_path=str(edited_brief_path),
        diff_summary=diff_summary,
    )

    # Re-embed the new angle as a preferred-angle signal so future runs in
    # similar markets/ICPs surface it via RAG.
    if angle_changed:
        # Recover ICP summary from the episodic log of the original run.
        icp_summary = _recover_icp_summary(memory, run_id) or _extract(_ICP_LINE_RE, edited) or ""
        semantic.index_brief(
            run_id=f"{run_id}::edited",
            market=run["market"],
            icp_summary=icp_summary,
            angle=edited_angle,
            brief_path=str(edited_brief_path),
        )

    return FeedbackOutcome(
        run_id=run_id,
        captured=True,
        angle_changed=angle_changed,
        original_angle=original_angle,
        edited_angle=edited_angle,
        diff_lines_changed=lines_changed,
    )


def _recover_icp_summary(memory: EpisodicMemory, run_id: str) -> str | None:
    """Pull the ICP summary used at the original run from the episodic log
    (define_icp output's first segment, formatted as in agent._icp_summary)."""
    for inv in memory.get_invocations(run_id):
        if inv["skill_name"] != "define_icp" or not inv.get("output_json"):
            continue
        try:
            payload = json.loads(inv["output_json"])
            seg = (payload.get("segments") or [None])[0] or {}
            label = seg.get("segment_label", "")
            persona = seg.get("persona", {}) or {}
            firm = seg.get("firmographic", {}) or {}
            role = persona.get("role_job_title", "")
            pains = ", ".join((firm.get("strategic_pain_points") or [])[:3])
            if label or role:
                return f"{label} | {role} | pains: {pains}"
        except json.JSONDecodeError:
            continue
    return None
