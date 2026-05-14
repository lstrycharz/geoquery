"""SemanticMemory — index briefs, retrieve similar ones, sqlite-vec wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from memory import SemanticMemory


def _index(
    mem: SemanticMemory,
    run_id: str,
    market: str,
    icp: str,
    angle: str,
    *,
    eval_score: float = 1.0,
    section_skeleton: str = "",
) -> None:
    mem.index_brief(
        run_id=run_id,
        market=market,
        icp_summary=icp,
        angle=angle,
        brief_path=f"/briefs/{run_id}.md",
        eval_score=eval_score,
        section_skeleton=section_skeleton,
    )


def test_index_and_retrieve_finds_self(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    _index(mem, "r1", "B2B SaaS KM", "engineering lead", "bus-factor framing")

    hits = mem.find_similar(
        market="B2B SaaS KM",
        icp_summary="engineering lead",
        angle_hint="bus-factor framing",
        k=3,
    )
    assert len(hits) == 1
    assert hits[0].run_id == "r1"


def test_retrieve_orders_by_distance(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    _index(mem, "r1", "B2B SaaS KM", "engineering lead", "bus-factor framing")
    _index(mem, "r2", "DTC CPG cosmetics", "founder", "unboxing-first launch")
    _index(mem, "r3", "B2B SaaS KM", "engineering lead", "bus-factor framing")

    hits = mem.find_similar(
        market="B2B SaaS KM",
        icp_summary="engineering lead",
        angle_hint="bus-factor framing",
        k=3,
    )
    # Top hit should be one of r1/r3 (identical signature) before r2.
    assert hits[0].run_id in {"r1", "r3"}
    # The last hit should be the dissimilar one.
    assert hits[-1].run_id == "r2"


def test_find_similar_returns_empty_when_store_is_empty(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    assert mem.find_similar(market="m", icp_summary="i") == []


# ---------------------------------------------------------------------------
# v3 chunk 1 — score-aware memory
# ---------------------------------------------------------------------------


def test_index_brief_stores_eval_score_and_section_skeleton(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    _index(
        mem,
        "r1",
        "B2B SaaS KM",
        "engineering lead",
        "bus-factor framing",
        eval_score=0.86,
        section_skeleton="The bus-factor problem | Markdown vs WYSIWYG | 30-day pilot",
    )
    hit = mem.find_similar(market="B2B SaaS KM", icp_summary="engineering lead", k=3)[0]
    assert hit.eval_score == 0.86
    assert "bus-factor problem" in hit.section_skeleton


def test_index_brief_eval_score_defaults_to_one(tmp_path: Path, stub_embedder):
    """Backward-compat: callers that don't pass eval_score get 1.0 (neutral)."""
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    mem.index_brief(
        run_id="r1",
        market="m",
        icp_summary="i",
        angle="a",
        brief_path="/briefs/r1.md",
    )
    hit = mem.find_similar(market="m", icp_summary="i", k=3)[0]
    assert hit.eval_score == 1.0
    assert hit.section_skeleton == ""


def test_schema_migration_adds_columns_to_legacy_db(tmp_path: Path, stub_embedder):
    """An episodic.db created before v3 has no eval_score column. Opening it with
    the v3 SemanticMemory must ALTER the columns in, not crash."""
    db_path = tmp_path / "sem.db"
    # Hand-build the v2-era `briefs` table — no eval_score / section_skeleton.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE briefs (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL, market TEXT NOT NULL, icp_summary TEXT NOT NULL,
            angle TEXT NOT NULL, brief_path TEXT NOT NULL, created_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.close()

    # v3 constructor should migrate the legacy table additively.
    mem = SemanticMemory(db_path=db_path, embedder=stub_embedder)
    cols = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(briefs)")}
    assert {"eval_score", "eval_details_json", "section_skeleton"} <= cols
    # And it's usable after migration.
    _index(mem, "r1", "m", "i", "a", eval_score=0.5)
    assert mem.find_similar(market="m", icp_summary="i", k=3)[0].eval_score == 0.5


def test_find_similar_default_still_ranks_by_distance(tmp_path: Path, stub_embedder):
    """Default behavior unchanged: rank_by_eval_score=False ranks by distance,
    ignoring eval_score entirely."""
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    # r1/r3 share a signature (near distance 0); r2 is dissimilar. r2 has the
    # highest eval_score — but with distance ranking it must still come last.
    _index(mem, "r1", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=0.10)
    _index(mem, "r2", "DTC CPG cosmetics", "founder", "unboxing", eval_score=0.99)
    _index(mem, "r3", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=0.10)

    hits = mem.find_similar(
        market="B2B SaaS KM", icp_summary="eng lead", angle_hint="bus-factor", k=3
    )
    assert hits[0].run_id in {"r1", "r3"}
    assert hits[-1].run_id == "r2"  # dissimilar, despite the high score


def test_find_similar_rank_by_eval_score_floats_high_scorers_up(tmp_path: Path, stub_embedder):
    """rank_by_eval_score=True: among the distance-candidate set, re-rank so the
    highest eval_score comes first."""
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    # Three near-identical-signature briefs with different eval scores.
    _index(mem, "low", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=0.30)
    _index(mem, "high", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=0.95)
    _index(mem, "mid", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=0.60)

    hits = mem.find_similar(
        market="B2B SaaS KM",
        icp_summary="eng lead",
        angle_hint="bus-factor",
        k=3,
        rank_by_eval_score=True,
    )
    assert [h.run_id for h in hits] == ["high", "mid", "low"]


def test_find_similar_rank_by_eval_score_returns_at_most_k(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    for i in range(8):
        _index(mem, f"r{i}", "B2B SaaS KM", "eng lead", "bus-factor", eval_score=i / 10)
    hits = mem.find_similar(
        market="B2B SaaS KM", icp_summary="eng lead", k=5, rank_by_eval_score=True
    )
    assert len(hits) == 5
    # Highest scorer (r7, 0.7) must be first.
    assert hits[0].run_id == "r7"


def test_top_scoring_briefs_orders_by_eval_score_desc(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    _index(mem, "low", "m", "i", "a", eval_score=0.30)
    _index(mem, "high", "m", "i", "a", eval_score=0.90)
    _index(mem, "mid", "m", "i", "a", eval_score=0.60)
    top = mem.top_scoring_briefs(limit=2)
    assert [b.run_id for b in top] == ["high", "mid"]


def test_top_scoring_briefs_returns_empty_on_empty_store(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    assert mem.top_scoring_briefs(limit=5) == []


def test_update_eval_score_overwrites_the_stored_value(tmp_path: Path, stub_embedder):
    mem = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    _index(mem, "r1", "m", "i", "a", eval_score=0.40)
    mem.update_eval_score("r1", 0.92)
    assert mem.top_scoring_briefs(limit=1)[0].eval_score == 0.92
