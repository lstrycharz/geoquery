"""End-to-end tracer-bullet test — cassettes for both skills, real episodic write,
real markdown file produced. Deterministic and free.
"""

from __future__ import annotations

from agent import run_brief
from memory import EpisodicMemory

# Skill cassettes (logged to episodic memory)
_SKILL_CASSETTES = (
    "research_company",
    "define_icp",
    "generate_geo_query_list",
    "score_queries",
    "select_priority_query",
    "analyze_serp",
    "draft_content_brief",
)
# Plus tool + judge cassettes (not logged as skill invocations but still loaded)
_OTHER_CASSETTES = (
    "serp_results",
    "judge_buyer_realism",
    "judge_brief_specificity",
)
_PIPELINE_CASSETTES = _SKILL_CASSETTES + _OTHER_CASSETTES


def _load_pipeline(fake_client) -> None:
    for name in _PIPELINE_CASSETTES:
        fake_client.load_cassette(name)


def test_run_brief_produces_brief_file_and_logs_each_skill(
    fake_client, tmp_settings, stub_embedder
):
    _load_pipeline(fake_client)

    outcome = run_brief(
        company="Notion",
        market="B2B SaaS knowledge management",
        settings=tmp_settings,
        client=fake_client,
        embedder=stub_embedder,
    )

    assert outcome.status == "completed"
    assert outcome.brief_path is not None
    assert outcome.brief_path.is_file()
    assert outcome.total_cost_usd > 0

    content = outcome.brief_path.read_text()
    assert "Content Brief" in content
    assert "Angle" in content
    assert "Structure" in content

    mem = EpisodicMemory(db_path=tmp_settings.data_dir / "episodic.db")
    run = mem.get_run(outcome.run_id)
    assert run is not None
    assert run["status"] == "completed"
    invocations = mem.get_invocations(outcome.run_id)
    assert [i["skill_name"] for i in invocations] == list(_SKILL_CASSETTES)
    assert all(i["cost_usd"] > 0 for i in invocations)
    # Chunk 6: every invocation should have eval_passed = 1 (cassette outputs pass)
    assert all(i["eval_passed"] == 1 for i in invocations)


def test_run_brief_records_aborted_cost_when_cap_is_too_low(
    fake_client, tmp_settings, monkeypatch, stub_embedder
):
    _load_pipeline(fake_client)
    # Force cap below first-skill projected cost
    monkeypatch.setattr(tmp_settings, "max_cost_usd", 0.0001)

    outcome = run_brief(
        company="X",
        market="Y",
        settings=tmp_settings,
        client=fake_client,
        embedder=stub_embedder,
    )
    assert outcome.status == "aborted_cost"
    assert outcome.brief_path is None
