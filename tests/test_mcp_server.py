"""mcp_server — tool registration + structural smoke test.

We don't spin up the actual stdio loop in tests (that would block on
stdin). Instead, we verify the tool is registered with the FastMCP
instance and that its callable shape matches the contract.
"""

from __future__ import annotations

import asyncio
import inspect


def test_mcp_server_registers_generate_brief_tool():
    from mcp_server import mcp

    # FastMCP exposes registered tools via an async list_tools() method.
    tools = asyncio.run(mcp.list_tools())
    names = [t.name for t in tools]
    assert "generate_brief" in names

    tool = next(t for t in tools if t.name == "generate_brief")
    # Tool must have a description that names the pipeline (sanity check
    # that the docstring made it through).
    assert tool.description
    assert "research_company" in tool.description or "brief" in tool.description.lower()
    # Input schema lists the parameters we expect.
    props = tool.inputSchema.get("properties", {})
    assert "company" in props
    assert "market" in props
    assert "sitemap" in props


def test_generate_brief_callable_signature():
    """Importing the underlying function must not require an Anthropic key —
    the call itself does, but the signature should be inspectable cold."""
    from mcp_server import generate_brief

    sig = inspect.signature(generate_brief)
    params = sig.parameters
    assert "company" in params
    assert "market" in params
    assert "sitemap" in params
    # sitemap should be optional.
    assert params["sitemap"].default is None
