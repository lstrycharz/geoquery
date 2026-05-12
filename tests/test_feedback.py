"""feedback — outer-loop edit capture + preferred-angle re-embedding."""

from __future__ import annotations

from pathlib import Path

import pytest

from feedback import capture_feedback
from memory import EpisodicMemory, SemanticMemory

_BRIEF_TEMPLATE = """# Content Brief — target query

_Run `RUNID` · Company: Acme · Market: B2B SaaS_

**ICP segment:** Director of Engineering — 200-person dev shop

**Audience:** Engineering directors at 200-person dev shops

**Angle:** {angle}

**Recommended length:** 2000 words

## Structure
"""


def _seed_run(settings, run_id: str, brief_text: str) -> Path:
    """Create a 'completed' run in episodic memory plus a draft_content_brief
    invocation row, and write the brief markdown file."""
    mem = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    # Manually insert the run + invocation rows (bypass the start_run UUID).
    from memory.episodic import SkillInvocationRecord, _now

    with mem._connect() as conn:
        conn.execute(
            "INSERT INTO runs (id, started_at, ended_at, company, market, status, "
            "total_cost_usd, brief_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), _now(), "Acme", "B2B SaaS", "completed", 0.5, None),
        )

    brief_path = settings.output_dir / f"{run_id}.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(brief_text, encoding="utf-8")

    with mem._connect() as conn:
        conn.execute("UPDATE runs SET brief_path = ? WHERE id = ?", (str(brief_path), run_id))

    # Insert a define_icp invocation row so feedback._recover_icp_summary works.
    mem.log_skill_invocation(
        SkillInvocationRecord(
            run_id=run_id,
            skill_name="define_icp",
            attempt=1,
            model="claude-sonnet-4-6",
            input_json="{}",
            output_json=(
                '{"segments": [{"segment_label": "Director of Engineering",'
                ' "firmographic": {"strategic_pain_points": ["search at scale"]},'
                ' "persona": {"role_job_title": "Director of Engineering"}}]}'
            ),
            cost_usd=0.05,
            started_at=_now(),
        )
    )

    return brief_path


def test_capture_records_human_edit_row(tmp_settings, stub_embedder):
    original = _BRIEF_TEMPLATE.format(angle="Original angle text here that we plan to change.")
    _seed_run(tmp_settings, "run-a", original)

    edited_path = tmp_settings.output_dir / "edited.md"
    edited = original.replace(
        "Original angle text here that we plan to change.",
        "Way sharper angle the human prefers, with concrete framing.",
    )
    edited_path.write_text(edited, encoding="utf-8")

    outcome = capture_feedback(
        run_id="run-a",
        edited_brief_path=edited_path,
        settings=tmp_settings,
        embedder=stub_embedder,
    )

    assert outcome.captured
    assert outcome.angle_changed
    assert "Way sharper" in outcome.edited_angle
    assert outcome.diff_lines_changed >= 2

    # human_edits row was created
    mem = EpisodicMemory(db_path=tmp_settings.data_dir / "episodic.db")
    rows = mem.get_human_edits("run-a")
    assert len(rows) == 1
    assert "Way sharper" in rows[0]["diff_summary"]


def test_preferred_angle_re_embeds_into_semantic_memory(tmp_settings, stub_embedder):
    original = _BRIEF_TEMPLATE.format(angle="Original angle one two three four five.")
    _seed_run(tmp_settings, "run-b", original)
    edited_path = tmp_settings.output_dir / "edited.md"
    edited_path.write_text(
        original.replace(
            "Original angle one two three four five.", "Edited angle text materially different."
        ),
        encoding="utf-8",
    )

    capture_feedback(
        run_id="run-b",
        edited_brief_path=edited_path,
        settings=tmp_settings,
        embedder=stub_embedder,
    )

    # The new angle should now be retrievable in semantic memory.
    sem = SemanticMemory(db_path=tmp_settings.data_dir / "semantic.db", embedder=stub_embedder)
    hits = sem.find_similar(
        market="B2B SaaS",
        icp_summary="Director of Engineering | Director of Engineering | pains: search at scale",
        angle_hint="Edited angle text materially different.",
        k=1,
    )
    assert hits
    assert hits[0].run_id == "run-b::edited"


def test_capture_raises_if_run_missing(tmp_settings, stub_embedder, tmp_path):
    edited = tmp_path / "x.md"
    edited.write_text("# anything", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        capture_feedback(
            run_id="nonexistent",
            edited_brief_path=edited,
            settings=tmp_settings,
            embedder=stub_embedder,
        )


def test_capture_no_op_when_angle_unchanged(tmp_settings, stub_embedder):
    text = _BRIEF_TEMPLATE.format(angle="Angle stays exactly the same here.")
    _seed_run(tmp_settings, "run-c", text)
    edited_path = tmp_settings.output_dir / "edited.md"
    edited_path.write_text(text + "\n(typo fix elsewhere)", encoding="utf-8")

    outcome = capture_feedback(
        run_id="run-c",
        edited_brief_path=edited_path,
        settings=tmp_settings,
        embedder=stub_embedder,
    )
    assert not outcome.angle_changed
    # human_edits row still created (for any-edit auditing) but no semantic-memory write.
    mem = EpisodicMemory(db_path=tmp_settings.data_dir / "episodic.db")
    assert len(mem.get_human_edits("run-c")) == 1
