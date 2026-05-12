# GEO Query → Content Brief Agent

> Most "agents" are one big prompt. This one is decomposed across six layers — skills, tools, evals, guardrails, memory, and feedback — so that each architectural decision is visible, testable, and replaceable. The README is part of the deliverable: it teaches the decomposition, not just the feature.

Given `(company, market)`, the agent produces a complete SEO content brief in ~10–15 minutes for ~$0.30–$0.60. Eight real example briefs across industries live under [`briefs/`](./briefs/).

## What it does

```
company + market
  → research_company         CASINO 11-section dossier  (Sonnet)
  → define_icp               2–4 firmographic + persona segments  (Sonnet)
  → generate_geo_query_list  25-query buyer journey, 5 framings  (Haiku ← non-negotiable per source skill)
  → score_queries            traffic / KD / business-value scoring  (Sonnet; real volume + KD if DataForSEO set)
  → select_priority_query    strategic pick, not pure argmax  (Sonnet)
  → analyze_serp             top-3 page content fetched + synthesized  (Sonnet)
  → draft_content_brief      SERP- + RAG-informed + sitemap-grounded  (Sonnet, streaming)
```

## Six-layer architecture

```
                          INTERFACES
        ┌─────────────────────────────────────────────────┐
        │  cli.py  (Typer)        │  mcp_server.py  (MCP) │
        └─────────────────────────────────────────────────┘
                                │
        ┌───────────────────────▼────────────────────────────────────┐
        │ ORCHESTRATOR  agent.run_brief()                              │
        │   research_company → define_icp → generate_geo_query_list    │
        │   → score_queries → select_priority_query → analyze_serp     │
        │   → draft_content_brief                                      │
        └──────────────────────────────────────────────────────────────┘
                                │
   ┌────────┬──────────────┬────┴────────────┬──────────────┬─────────────┐
   │SKILLS  │  TOOLS       │ EVALS           │ GUARDRAILS   │ MEMORY      │
   │ 7 deep │ web_search   │ deterministic   │ RunBudget    │ episodic    │
   │ modules│ web_fetch    │ + model-graded  │ (cost +      │ (SQLite,    │
   │ (prompt│   (SSRF)     │   judges        │  retry caps) │  versioned) │
   │ + ctr  │ dataforseo   │ + golden        │              │ + semantic  │
   │ + model│   (hybrid)   │   regression    │              │ (sqlite-vec │
   │ + evals│ sitemap      │   set           │              │ + fastembed)│
   │ )      │ slack_notify │                 │              │             │
   └────────┴──────────────┴─────────────────┴──────────────┴─────────────┘
                                │
                ┌───────────────▼───────────────────────────┐
                │ FEEDBACK                                   │
                │  Inner loop (sync): eval fail → revise     │
                │   (capped at 3 attempts per skill)         │
                │  Outer loop (async): geoquery feedback     │
                │   captures human edits → preferred-angle   │
                │   re-embed into semantic memory            │
                └────────────────────────────────────────────┘
```

| Layer | Role | Where it lives |
|---|---|---|
| **Skills** | The unit of reasoning. One prompt + one Pydantic contract + one model + owned evaluators. | [`skills/`](./skills/) — 7 deep modules, prompts in `skills/prompts/*.md`. |
| **Tools** | External, deterministic interfaces. Skills *call* these; they don't reason. | [`tools/`](./tools/) — `web_search` (Anthropic native), `web_fetch` (SSRF-hardened), `dataforseo` (hybrid), `sitemap_parser`, `slack_notify`. |
| **Evals** | Verify each skill's output. Deterministic shape checks **block** revision; model-graded judges are **advisory**. | [`evals/`](./evals/) — `deterministic.py`, `model_graded.py`, `golden_set.py`. |
| **Guardrails** | One `RunBudget` owns cost cap + per-skill retry cap. | [`guardrails/limits.py`](./guardrails/limits.py). |
| **Memory** | Episodic write log + semantic recall. | [`memory/episodic.py`](./memory/episodic.py) (SQLite) + [`memory/semantic.py`](./memory/semantic.py) (sqlite-vec + fastembed). |
| **Feedback** | Inner loop (eval fail → revise) + outer loop (human edit → preferred-angle re-embed). | `Skill.run` revision header + [`feedback.py`](./feedback.py) + `geoquery feedback` CLI subcommand. |

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full per-layer decision log.

## Quick start

```bash
git clone <repo-url> && cd GEOQuery

# Either: Docker (zero local Python setup)
cp .env.example .env   # paste your ANTHROPIC_API_KEY
docker compose run --rm geoquery brief --company "Notion" --market "B2B SaaS knowledge management"

# Or: local Python (needs Brew Python 3.13+ on macOS for sqlite extension support)
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[semantic,web,report,mcp,dev]"
cp .env.example .env   # paste keys
geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

### Environment (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...                # required
DATAFORSEO_LOGIN=...                        # optional: real volume + KD + CPC
DATAFORSEO_PASSWORD=...                     # optional
SLACK_WEBHOOK_URL=https://hooks.slack.com/  # optional: notify on completion
MAX_COST_USD=3.0                            # default $3 per run
```

When DataForSEO credentials are absent, `score_queries` falls back to LLM-estimated metrics — the agent still runs end-to-end. (Earlier draft of the architecture had this as a hard requirement; flipped for cloneability — see `ARCHITECTURE.md`.)

## What you'll see when you run it

```
$ geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
→ research_company
  ✓ research_company  0.0735$  attempt=1
→ define_icp
  ✓ define_icp  0.0563$  attempt=1
→ generate_geo_query_list  (Haiku)
  ✓ generate_geo_query_list  0.0089$
→ dataforseo (real metrics)
  ✓ dataforseo  18/25 queries hit
→ score_queries
  ✓ score_queries  0.0421$
→ select_priority_query
  ✓ select_priority_query  0.0234$
    picked: 'alternatives to notion for engineering documentation'
→ web_search + web_fetch (top-3 pages)
  ✓ fetched 3/3 pages, 10 results total
→ analyze_serp
  ✓ analyze_serp  0.0589$
→ draft_content_brief  (streaming, similar=2)
    ...streamed 4200 chars
    ...streamed 8400 chars
    ...streamed 12600 chars
  ✓ draft_content_brief  0.0734$

run_id: 54abf2d7-b317-4c89-ab24-80213a029c48
brief:  briefs/54abf2d7_notion_alternatives-to-notion-for-engineering-documentation.md
cost:   $0.3322
```

## CLI

```
geoquery brief --company X --market Y [--sitemap https://x.com/sitemap.xml]
geoquery runs                        # list past runs
geoquery show <run-id>               # run metadata + skill invocations
geoquery feedback <run-id> --edited path/to/edited.md   # capture human edits
geoquery eval-golden [--report]      # run the regression set
```

## MCP server

`mcp_server.py` exposes `generate_brief(company, market, sitemap?)` over MCP stdio. Configure Claude Desktop:

```json
{
  "mcpServers": {
    "geoquery": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/GEOQuery"
    }
  }
}
```

Then in any chat: *"use the `generate_brief` tool to draft a brief for Notion in B2B SaaS knowledge management."*

## Example briefs

Eight real-API-generated briefs across industries live under [`briefs/`](./briefs/):

| File | Industry | Angle |
|---|---|---|
| [example_notion_b2b_saas_knowledge_mgmt.md](./briefs/example_notion_b2b_saas_knowledge_mgmt.md) | B2B SaaS — KM | Single source of truth for product + engineering docs |
| [example_linear_b2b_saas_project_mgmt.md](./briefs/example_linear_b2b_saas_project_mgmt.md) | B2B SaaS — PM | Linear vs Jira for 20-person engineering team |
| [example_glossier_dtc_beauty.md](./briefs/example_glossier_dtc_beauty.md) | DTC beauty | Good ingredients under $30 skincare brands |
| [example_stripe_payments_fintech.md](./briefs/example_stripe_payments_fintech.md) | Fintech infra | Billing reconciliation nightmare with Stripe |
| [example_webflow_nocode_design.md](./briefs/example_webflow_nocode_design.md) | No-code | Figma-to-live animation in a no-code builder |
| [example_hubspot_smb_crm.md](./briefs/example_hubspot_smb_crm.md) | SMB CRM | CRM with built-in email workflows (no Zapier) |
| [example_vercel_frontend_cloud.md](./briefs/example_vercel_frontend_cloud.md) | Frontend cloud | Alternatives to Vercel with predictable billing |
| [example_patagonia_dtc_outdoor.md](./briefs/example_patagonia_dtc_outdoor.md) | DTC outdoor | Brands with lifetime repair programs |

Total cost to generate all 8: **$3.85**.

## Testing

```bash
pytest -q       # 84 tests, ~3s, cassette-driven, $0 LLM cost
ruff check .    # lint
ruff format .   # format
```

Test cassettes live under `tests/fixtures/cassettes/`. They keep CI fast and free. Real LLM regression is gated by `geoquery eval-golden`.

## Cost discipline

- One `RunBudget` per run, default `$3`. Per-skill `register_attempt` enforces a 3-attempt cap.
- Typical happy-path cost: ~$0.30 (no research_company / DataForSEO) to ~$0.60 (full pipeline).
- Streaming runs charge the same as non-streaming; the streaming is for UX only.

## Status

Built incrementally over 19 chunks. See [`tasks/todo.md`](./tasks/todo.md) for chunk-level history and [`tasks/lessons.md`](./tasks/lessons.md) for corrections that landed as code changes.

## License

MIT.
