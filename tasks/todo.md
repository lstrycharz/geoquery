# Chunked Build — GEO Query → Content Brief Agent

Each chunk: red → green → refactor → commit. Vertical-slice first (chunks 1–8 ship a working v1); stretches additive (9–19).

## Vertical slice
- [x] **Chunk 1 — Tracer bullet**: project skeleton, `Skill` base, `define_icp`, placeholder `draft_content_brief`, episodic memory, `RunBudget`, Typer CLI, E2E smoke test. README outline + ARCHITECTURE skeleton committed. 19/19 tests green, ruff clean.
- [x] **Chunk 2** — `generate_geo_query_list` (Haiku, single prompt, 5 buyer framings). 23/23 tests green, ruff clean. Placeholder priority-query picker until ch3 lands.
- [x] **Chunk 3** — `score_queries` (LLM-only) + `select_priority_query` (strategic, not argmax). 27/27 green, ruff clean. Placeholder priority-query picker retired.
- [ ] **Chunk 4** — `tools/web_search.py` + `analyze_serp` (snippets only).
- [ ] **Chunk 5** — Replace placeholder `draft_content_brief` with real SERP-snippet-informed version.
- [ ] **Chunk 6** — Deterministic + model-graded evals + inner-loop revision.
- [ ] **Chunk 7** — `memory/semantic.py` (fastembed + sqlite-vec) + RAG injection into drafter.
- [ ] **Chunk 8** — Generate 3 example briefs; verify v1 pipeline holds.

## Stretches (additive, no regression to v1)
- [ ] **Chunk 9** — `research_company` (7th skill upstream; `define_icp` consumes dossier).
- [ ] **Chunk 10** — `tools/web_fetch.py` (SSRF-hardened) → `analyze_serp` reads top-3 pages.
- [ ] **Chunk 11** — `tools/dataforseo.py` → `score_queries` uses real volume/KD; competitor URLs.
- [ ] **Chunk 12** — `tools/sitemap_parser.py` → grounded internal linking in briefs.
- [ ] **Chunk 13** — Golden regression set + `eval-golden` command + `--report` HTML.
- [ ] **Chunk 14** — `geoquery feedback` subcommand; preferred-angle embeddings.
- [ ] **Chunk 15** — Streaming output for `draft_content_brief` (tokens to stdout).
- [ ] **Chunk 16** — `mcp_server.py` (MCP stdio transport).
- [ ] **Chunk 17** — Dockerfile + docker-compose + pre-commit hook (ruff + pytest).
- [ ] **Chunk 18** — Remaining 4–7 example briefs (target 5–10 total, distinct industries).
- [ ] **Chunk 19** — Final README + ARCHITECTURE pass.
