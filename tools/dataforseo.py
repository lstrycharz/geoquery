"""dataforseo — hybrid keyword-metrics tool.

When `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` are set, this tool fetches
real search volume, CPC, and (optionally) keyword difficulty per query from
DataForSEO's API. When credentials are missing, `fetch_keyword_metrics`
returns an empty dict and `score_queries` falls back to LLM-estimated metrics.

This is the canonical illustration of the "Tools layer is the boundary to
the outside world" principle:
- credentials live in `config.py`'s `Settings`, not in this module
- the function is total (returns {} on any failure rather than raising)
- the cost contribution is recorded on the RunBudget

We make at most 2 API calls per run (search volume + KD), batched across all
25 queries. Each call is ~$0.05; the typical cost per run with DataForSEO
enabled is ~$0.10.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from contracts import KeywordMetrics
from guardrails import RunBudget

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_TIMEOUT_SECONDS = 30.0
_FLAT_COST_USD = 0.10  # search_volume + bulk_kd, two calls per run


def _auth_header(login: str, password: str) -> str:
    token = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def fetch_keyword_metrics(
    *,
    login: str,
    password: str,
    queries: list[str],
    budget: RunBudget,
    location_code: int = 2840,  # United States
    language_code: str = "en",
) -> dict[str, KeywordMetrics]:
    """Returns {query_text: KeywordMetrics} for queries DataForSEO has data on.

    Queries with no data are simply absent from the result (the caller treats
    missing entries as "no real metrics available, score with LLM estimation").
    On any API/network failure, returns {} (degraded but never breaks the run).
    """
    if not (login and password and queries):
        return {}

    budget.check_can_spend(_FLAT_COST_USD)
    budget.record_spend(_FLAT_COST_USD)

    auth = _auth_header(login, password)
    headers = {"Authorization": auth, "Content-Type": "application/json"}

    metrics_by_query: dict[str, KeywordMetrics] = {q: KeywordMetrics() for q in queries}

    # --- search_volume: returns volume + CPC + competition_index ---
    sv_payload = [
        {
            "keywords": queries,
            "location_code": location_code,
            "language_code": language_code,
        }
    ]
    sv_results = _post(
        "/v3/keywords_data/google_ads/search_volume/live",
        sv_payload,
        headers=headers,
    )
    for item in _iter_results(sv_results):
        keyword = item.get("keyword")
        if not keyword or keyword not in metrics_by_query:
            continue
        m = metrics_by_query[keyword]
        m.volume = item.get("search_volume")
        m.cpc = _safe_float(item.get("cpc"))

    # --- bulk_keyword_difficulty: returns KD per keyword ---
    kd_payload = [
        {
            "keywords": queries,
            "location_code": location_code,
            "language_code": language_code,
        }
    ]
    kd_results = _post(
        "/v3/dataforseo_labs/google/bulk_keyword_difficulty/live",
        kd_payload,
        headers=headers,
    )
    for item in _iter_results(kd_results):
        keyword = item.get("keyword")
        if not keyword or keyword not in metrics_by_query:
            continue
        metrics_by_query[keyword].kd = _safe_float(item.get("keyword_difficulty"))

    return {q: m for q, m in metrics_by_query.items() if m.volume is not None or m.kd is not None}


def _post(path: str, payload: list[dict], *, headers: dict[str, str]) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=httpx.Timeout(_TIMEOUT_SECONDS)) as client:
            response = client.post(f"{_BASE_URL}{path}", json=payload, headers=headers)
        if response.status_code // 100 != 2:
            logger.info("dataforseo: non-2xx %s for %s", response.status_code, path)
            return None
        return response.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.info("dataforseo: %s for %s", type(e).__name__, path)
        return None
    except ValueError:
        logger.info("dataforseo: non-JSON response for %s", path)
        return None


def _iter_results(envelope: dict[str, Any] | None):
    """DataForSEO response envelope: tasks -> result -> items."""
    if not envelope:
        return
    for task in envelope.get("tasks") or []:
        for res in task.get("result") or []:
            items = res.get("items") if isinstance(res, dict) else None
            if isinstance(items, list):
                yield from items
            elif isinstance(res, dict):
                yield res


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
