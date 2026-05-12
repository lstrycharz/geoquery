"""tools/dataforseo — hybrid: returns {} without credentials, parses on success."""

from __future__ import annotations

from guardrails import RunBudget
from tools import dataforseo
from tools.dataforseo import fetch_keyword_metrics


def test_returns_empty_without_credentials():
    result = fetch_keyword_metrics(
        login="", password="", queries=["x"], budget=RunBudget(max_cost_usd=3.0)
    )
    assert result == {}


def test_returns_empty_without_queries():
    result = fetch_keyword_metrics(
        login="user", password="pw", queries=[], budget=RunBudget(max_cost_usd=3.0)
    )
    assert result == {}


def test_parses_search_volume_and_kd(monkeypatch):
    """Stub the DataForSEO API; verify the two-endpoint merge."""

    def _fake_post(path, payload, *, headers):
        if "search_volume" in path:
            return {
                "tasks": [
                    {
                        "result": [
                            {
                                "items": [
                                    {"keyword": "alpha", "search_volume": 1200, "cpc": 4.5},
                                    {"keyword": "beta", "search_volume": 90, "cpc": None},
                                ]
                            }
                        ]
                    }
                ]
            }
        if "bulk_keyword_difficulty" in path:
            return {
                "tasks": [
                    {
                        "result": [
                            {
                                "items": [
                                    {"keyword": "alpha", "keyword_difficulty": 62},
                                    {"keyword": "beta", "keyword_difficulty": 18},
                                ]
                            }
                        ]
                    }
                ]
            }
        return None

    monkeypatch.setattr(dataforseo, "_post", _fake_post)

    metrics = fetch_keyword_metrics(
        login="u",
        password="p",
        queries=["alpha", "beta", "gamma"],
        budget=RunBudget(max_cost_usd=3.0),
    )
    assert set(metrics.keys()) == {"alpha", "beta"}  # gamma has no data, omitted
    assert metrics["alpha"].volume == 1200
    assert metrics["alpha"].cpc == 4.5
    assert metrics["alpha"].kd == 62.0
    assert metrics["beta"].volume == 90
    assert metrics["beta"].kd == 18.0


def test_charges_budget(monkeypatch):
    monkeypatch.setattr(dataforseo, "_post", lambda *a, **kw: None)
    budget = RunBudget(max_cost_usd=3.0)
    fetch_keyword_metrics(login="u", password="p", queries=["a"], budget=budget)
    assert budget.spent_usd > 0


def test_returns_empty_when_api_fails(monkeypatch):
    monkeypatch.setattr(dataforseo, "_post", lambda *a, **kw: None)
    metrics = fetch_keyword_metrics(
        login="u", password="p", queries=["a", "b"], budget=RunBudget(max_cost_usd=3.0)
    )
    assert metrics == {}
