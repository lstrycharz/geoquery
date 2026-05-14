"""evals/winning_patterns.py — periodic structural-pattern extractor."""

from __future__ import annotations

from pathlib import Path

from evals.winning_patterns import extract_winning_patterns
from guardrails import RunBudget
from memory import EpisodicMemory, SemanticMemory


def _index_high_scorers(semantic: SemanticMemory, n: int) -> None:
    for i in range(n):
        semantic.index_brief(
            run_id=f"r{i}",
            market="B2B SaaS knowledge mgmt",
            icp_summary="engineering lead",
            angle=f"the bus-factor angle {i}",
            brief_path=f"/briefs/r{i}.md",
            eval_score=0.80 + i * 0.01,
            section_skeleton="The bus-factor problem | Markdown vs WYSIWYG | 30-day pilot",
        )


def test_extract_winning_patterns_calls_llm_and_records(tmp_path: Path, stub_embedder, fake_client):
    semantic = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    episodic = EpisodicMemory(db_path=tmp_path / "ep.db")
    _index_high_scorers(semantic, 6)
    fake_client.load_cassette("winning_patterns")
    budget = RunBudget(max_cost_usd=5.0)

    patterns = extract_winning_patterns(
        semantic=semantic, episodic=episodic, client=fake_client, budget=budget, top_n=5
    )

    assert patterns  # non-empty list of structural patterns
    latest = episodic.get_latest_winning_patterns()
    assert latest is not None
    assert latest["patterns"] == patterns
    assert latest["briefs_analyzed"] == 5  # capped at top_n


def test_extract_winning_patterns_no_briefs_is_a_noop(tmp_path: Path, stub_embedder, fake_client):
    """Nothing scored yet → nothing to learn from. No LLM call, no row."""
    semantic = SemanticMemory(db_path=tmp_path / "sem.db", embedder=stub_embedder)
    episodic = EpisodicMemory(db_path=tmp_path / "ep.db")
    budget = RunBudget(max_cost_usd=5.0)

    patterns = extract_winning_patterns(
        semantic=semantic, episodic=episodic, client=fake_client, budget=budget
    )

    assert patterns == []
    assert episodic.get_latest_winning_patterns() is None
