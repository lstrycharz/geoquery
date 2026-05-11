"""SemanticMemory — index briefs, retrieve similar ones, sqlite-vec wiring."""

from __future__ import annotations

from pathlib import Path

from memory import SemanticMemory


def _index(mem: SemanticMemory, run_id: str, market: str, icp: str, angle: str) -> None:
    mem.index_brief(
        run_id=run_id,
        market=market,
        icp_summary=icp,
        angle=angle,
        brief_path=f"/briefs/{run_id}.md",
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
