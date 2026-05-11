# GEO Query → Content Brief Agent

> Most "agents" are one big prompt. This one is decomposed across six layers — skills, tools, evals, guardrails, memory, and feedback — so that each architectural decision is visible, testable, and replaceable. The README is part of the deliverable: it teaches the decomposition, not just the feature.

## What it does

Given `(company, market)`, the agent produces a complete SEO content brief in ~10–15 minutes:

```
company + market
  → company research dossier        (CASINO 11-section, chunk 9)
  → multi-segment ICP                (firmographic + persona, 2–4 segments)
  → 25-query buyer journey           (Haiku, 5 buyer framings in one prompt)
  → real-data-scored queries         (DataForSEO + LLM judgment)
  → priority (segment, query) pair   (qualitative tie-break, not argmax)
  → SERP analysis                    (top-3 pages fetched + extracted)
  → SERP-informed brief              (with sitemap-grounded internal links)
```

## Why six layers

| Layer | Role | This repo's implementation |
|---|---|---|
| **Skills** | The unit of reasoning. One prompt + one Pydantic contract + one model + owned evaluators. | `skills/` — 7 deep modules. |
| **Tools** | External, deterministic interfaces. The skills *call* these; they don't reason. | `tools/` — `web_search`, `web_fetch` (SSRF-hardened), `dataforseo`, `sitemap_parser`, `slack_notify`. |
| **Evals** | Verify each skill's output before it propagates. Three classes: deterministic, model-graded, golden regression. | `evals/` — pure functions + Haiku judges + a regression command. |
| **Guardrails** | Hard ceilings on cost, retries, and what can leave the system. | `guardrails/limits.py` — one `RunBudget`. |
| **Memory** | Episodic write log + semantic recall. | `memory/episodic.py` (SQLite) + `memory/semantic.py` (sqlite-vec + fastembed). |
| **Feedback** | Inner loop (eval fail → revise) + outer loop (human edit → preferred-angle memory). | `Skill.run_with_revision` + `geoquery feedback` subcommand. |

Two interfaces sit on top of the orchestrator: a Typer CLI for humans, and an MCP server (`mcp_server.py`) so the agent can be called from Claude Code or Claude Desktop. Same code path either way.

## Quick start

```bash
cp .env.example .env   # fill in ANTHROPIC_API_KEY and DATAFORSEO_LOGIN/PASSWORD
pip install -e ".[dev]"
geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

Or via Docker (chunk 17):

```bash
docker compose run geoquery brief --company Notion --market "B2B SaaS knowledge management"
```

## Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for per-layer design decisions and tradeoffs. The short version:

```
                    INTERFACES
        ┌────────────────────────────────────────┐
        │  cli.py (Typer)    │  mcp_server.py    │
        └────────────────────────────────────────┘
                              │
        ┌─────────────────────▼──────────────────────────────────┐
        │ ORCHESTRATOR  (agent.py)                                │
        │  research_company → define_icp → generate_geo_query…    │
        │   → score_queries → select_priority → analyze_serp      │
        │   → draft_content_brief                                 │
        └─────────────────────────────────────────────────────────┘
                              │
   ┌────────┬─────────────────┼─────────────────┬───────────────┐
   │SKILLS  │  TOOLS         │ EVALS           │ GUARDRAILS    │ MEMORY
   └────────┴─────────────────┴─────────────────┴───────────────┘
                              │
                ┌─────────────▼──────────────────┐
                │ FEEDBACK  (inner + outer loops) │
                └─────────────────────────────────┘
```

## Status

Built in chunks; tracking lives in [`tasks/todo.md`](./tasks/todo.md). The repo is incremental — every chunk leaves the codebase in a working state, with tests green.

## License

MIT.
