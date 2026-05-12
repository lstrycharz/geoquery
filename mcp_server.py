"""MCP stdio server — exposes `generate_brief` to any MCP client.

This is the second interface on top of the same orchestrator. The CLI
(`cli.py`) is for humans; this server is for Claude Code, Claude Desktop, or
any MCP-compatible client that wants to call the agent as a tool.

Configure Claude Desktop's `claude_desktop_config.json`:

    {
      "mcpServers": {
        "geoquery": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "mcp_server"],
          "cwd": "/path/to/GEOQuery"
        }
      }
    }

Then in any chat: "use the generate_brief tool to draft a brief for Notion
in B2B SaaS knowledge management." The MCP client invokes the tool over
stdio; this server runs `run_brief` and returns the structured outcome.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from agent import run_brief

mcp = FastMCP("geoquery")


@mcp.tool()
def generate_brief(
    company: str,
    market: str,
    sitemap: str | None = None,
) -> dict:
    """Generate a complete SEO content brief for the given company + market.

    Pipeline: research_company → define_icp → generate_geo_query_list
    → score_queries → select_priority_query → analyze_serp → draft_content_brief.

    Args:
        company: Target company name (e.g. "Notion", "Glossier").
        market: Target market description (e.g. "B2B SaaS knowledge management").
        sitemap: Optional sitemap URL. When provided, internal-linking
            suggestions are grounded in real URLs from your site.

    Returns:
        A dict with the run_id, status, brief_path (when status == "completed"),
        total_cost_usd, and an optional error message.
    """
    outcome = run_brief(company=company, market=market, sitemap_url=sitemap)
    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "brief_path": str(outcome.brief_path) if outcome.brief_path else None,
        "total_cost_usd": outcome.total_cost_usd,
        "error": outcome.error,
    }


if __name__ == "__main__":
    mcp.run()
