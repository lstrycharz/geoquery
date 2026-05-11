"""tools/web_search — parses an emit_serp_results tool call into SerpResults."""

from __future__ import annotations

from contracts import SerpResult
from guardrails import RunBudget
from tools.web_search import search_top_n


def test_returns_parsed_serp_results(fake_client):
    # Cassette name = the part after 'emit_'
    fake_client.load_cassette("serp_results")
    budget = RunBudget(max_cost_usd=3.0)

    results = search_top_n(fake_client, budget, query="alternatives to notion for engineering")

    assert len(results) == 10
    assert all(isinstance(r, SerpResult) for r in results)
    assert results[0].rank == 1
    assert results[0].url.startswith("https://")
    # No page content yet (chunk 10 lands it)
    assert all(r.extracted_content is None for r in results)


def test_charges_budget(fake_client):
    fake_client.load_cassette("serp_results")
    budget = RunBudget(max_cost_usd=3.0)

    search_top_n(fake_client, budget, query="x")
    assert budget.spent_usd > 0
