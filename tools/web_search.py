"""web_search — Anthropic native server-side search wrapped as a deterministic tool.

The Anthropic Messages API exposes web search as a server-side tool. The model
decides when to issue searches; results come back in `web_search_tool_result`
content blocks. We hide that orchestration behind a single function that takes
a query and returns a list of SerpResult.

The function uses Haiku (cheap routing model) with a strict system prompt: it
must search, then emit results via the `emit_serp_results` client tool. We
parse the emitted structured output into the contract.

Cost accounting: input/output tokens are charged to the RunBudget; the search
tool itself has separate per-search pricing on Anthropic's side (~$10/1k
searches) which we model as a flat ~$0.01 per call to keep the budget honest.
"""

from __future__ import annotations

from anthropic import Anthropic

from contracts import SerpResult, SerpResultList
from guardrails import RunBudget
from skills.base import estimate_cost

WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
_MODEL = "claude-haiku-4-5"
_MAX_OUTPUT_TOKENS = 2048
_SEARCH_FLAT_USD = 0.01  # ~$10 / 1000 searches, charged once per call

_SYSTEM = (
    "You are a SERP-fetching tool. Use the `web_search` server tool to look up "
    "the user's query, then emit the top-N results via the `emit_serp_results` "
    "client tool. Do not add commentary. If web_search yields fewer than N "
    "results, emit what you have."
)


def search_top_n(
    client: Anthropic,
    budget: RunBudget,
    query: str,
    n: int = 10,
) -> list[SerpResult]:
    budget.check_can_spend(estimate_cost(_MODEL, 1500, _MAX_OUTPUT_TOKENS) + _SEARCH_FLAT_USD)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"Query: {query}\nFetch top {n} results."}],
        tools=[
            {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": 3},
            {
                "name": "emit_serp_results",
                "description": "Emit the top SERP results as structured data.",
                "input_schema": SerpResultList.model_json_schema(),
            },
        ],
    )

    cost = estimate_cost(_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    budget.record_spend(cost + _SEARCH_FLAT_USD)

    for block in response.content:
        if block.type == "tool_use" and block.name == "emit_serp_results":
            return SerpResultList.model_validate(block.input).results

    raise RuntimeError("web_search did not emit an emit_serp_results tool call")
