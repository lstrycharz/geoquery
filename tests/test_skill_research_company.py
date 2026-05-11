"""research_company — CASINO 11-section dossier."""

from __future__ import annotations

from contracts import CompanyDossier
from guardrails import RunBudget
from skills.research_company import ResearchCompany, ResearchCompanyInputs


def test_returns_validated_dossier(fake_client):
    fake_client.load_cassette("research_company")
    skill = ResearchCompany(client=fake_client, budget=RunBudget(max_cost_usd=3.0))

    result = skill.run(ResearchCompanyInputs(company="Notion", market="B2B SaaS"))

    dossier: CompanyDossier = result.output
    assert dossier.customer_segments
    assert dossier.product_portfolio
    assert dossier.inferred_icp
    assert dossier.competitors
    assert set(dossier.swot.keys()) == {"strengths", "weaknesses", "opportunities", "threats"}
    assert set(dossier.porter_five_forces.keys()) == {
        "buyer_power",
        "supplier_power",
        "rivalry",
        "new_entrants",
        "substitutes",
    }
    assert dossier.strategic_recommendations
    assert dossier.executable_work_plan
    assert result.eval_passed
