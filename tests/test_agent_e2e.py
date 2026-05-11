"""End-to-end tracer-bullet test — cassettes for both skills, real episodic write,
real markdown file produced. Deterministic and free.
"""

from __future__ import annotations

from agent import run_brief
from memory import EpisodicMemory


def test_run_brief_produces_brief_file_and_logs_two_invocations(fake_client, tmp_settings):
    fake_client.load_cassette("define_icp")
    fake_client.load_cassette("draft_content_brief")

    outcome = run_brief(
        company="Notion",
        market="B2B SaaS knowledge management",
        settings=tmp_settings,
        client=fake_client,
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
    assert [i["skill_name"] for i in invocations] == ["define_icp", "draft_content_brief"]
    assert all(i["cost_usd"] > 0 for i in invocations)


def test_run_brief_records_aborted_cost_when_cap_is_too_low(
    fake_client, tmp_settings, monkeypatch
):
    fake_client.load_cassette("define_icp")
    fake_client.load_cassette("draft_content_brief")
    # Force cap below first-skill projected cost
    monkeypatch.setattr(tmp_settings, "max_cost_usd", 0.0001)

    outcome = run_brief(
        company="X",
        market="Y",
        settings=tmp_settings,
        client=fake_client,
    )
    assert outcome.status == "aborted_cost"
    assert outcome.brief_path is None
