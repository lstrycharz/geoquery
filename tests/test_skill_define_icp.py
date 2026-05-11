"""define_icp skill — uses cassette to validate parse-and-charge flow."""

from __future__ import annotations

from contracts import ICPSegmentList
from guardrails import RunBudget
from skills.define_icp import DefineIcp, DefineIcpInputs


def test_define_icp_returns_validated_segments(fake_client):
    fake_client.load_cassette("define_icp")
    budget = RunBudget(max_cost_usd=3.0)
    skill = DefineIcp(client=fake_client, budget=budget)

    result = skill.run(DefineIcpInputs(company="Notion", market="B2B SaaS"))

    assert isinstance(result.output, ICPSegmentList)
    assert 2 <= len(result.output.segments) <= 4
    assert result.output.segments[0].segment_label
    assert result.attempt == 1
    assert result.cost_usd > 0
    assert budget.spent_usd == result.cost_usd


def test_define_icp_increments_budget_attempt(fake_client):
    fake_client.load_cassette("define_icp")
    budget = RunBudget(max_cost_usd=3.0)
    skill = DefineIcp(client=fake_client, budget=budget)

    r1 = skill.run(DefineIcpInputs(company="X", market="Y"))
    r2 = skill.run(DefineIcpInputs(company="X", market="Y"))
    assert r1.attempt == 1
    assert r2.attempt == 2
