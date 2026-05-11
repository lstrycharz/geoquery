# Chunked Build — GEO Query → Content Brief Agent

Each chunk: red → green → refactor → commit. Vertical-slice first (chunks 1–8 ship a working v1); stretches additive (9–19).

## Vertical slice
- [x] **Chunk 1 — Tracer bullet**: project skeleton, `Skill` base, `define_icp`, placeholder `draft_content_brief`, episodic memory, `RunBudget`, Typer CLI, E2E smoke test. README outline + ARCHITECTURE skeleton committed. 19/19 tests green, ruff clean.
- [x] **Chunk 2** — `generate_geo_query_list` (Haiku, single prompt, 5 buyer framings). 23/23 tests green, ruff clean. Placeholder priority-query picker until ch3 lands.
- [x] **Chunk 3** — `score_queries` (LLM-only) + `select_priority_query` (strategic, not argmax). 27/27 green, ruff clean. Placeholder priority-query picker retired.
- [x] **Chunk 4** — `tools/web_search.py` + `analyze_serp` (snippets only). 30/30 green. Tool returns `list[SerpResult]`; skill synthesizes common angles + content gaps.
- [x] **Chunk 5** — `draft_content_brief` is now SERP-informed. Inputs include `SerpAnalysis` (optional for backward-compat); prompt explicitly requires the angle to exploit a `content_gap` and call out a `common_angle` to differentiate from. 31/31 green.
- [x] **Chunk 6** — Deterministic + model-graded evals + inner-loop revision. Each skill owns its evaluator list; failures trigger re-run with revision header prepended (no cache_control so revisions are cheap). 49/49 green.
- [x] **Chunk 7** — `memory/semantic.py` (sqlite-vec + fastembed, 384-dim BGE-small). Drafter retrieves top-3 similar past briefs as "don't repeat" RAG context. 52/52 green. Note: requires SQLite with extension loading — Brew Python 3.13+ or Docker.
- [x] **Chunk 8** — V1 pipeline validated on 3 real runs (Notion / Linear / Glossier across B2B SaaS + DTC beauty), $0.99 total. Fixes landed: bump per-skill max_output_tokens to prevent mid-JSON truncation; defensive `_coerce_json_list` validators on contracts (model occasionally double-encodes nested arrays); `env_ignore_empty=True` so harness shell can't shadow `.env`; advisory vs blocking eval distinction (model-graded judges no longer gate the run on borderline calls).

## Stretches (additive, no regression to v1)
- [ ] **Chunk 9** — `research_company` (7th skill upstream; `define_icp` consumes dossier).
- [ ] **Chunk 10** — `tools/web_fetch.py` (SSRF-hardened) → `analyze_serp` reads top-3 pages.
- [ ] **Chunk 11** — `tools/dataforseo.py` (**hybrid**: works without credentials, uses real volume/KD when set) → `score_queries` consumes metrics when available; competitor URLs.
- [ ] **Chunk 12** — `tools/sitemap_parser.py` → grounded internal linking in briefs.
- [ ] **Chunk 13** — Golden regression set + `eval-golden` command + `--report` HTML.
- [ ] **Chunk 14** — `geoquery feedback` subcommand; preferred-angle embeddings.
- [ ] **Chunk 15** — Streaming output for `draft_content_brief` (tokens to stdout).
- [ ] **Chunk 16** — `mcp_server.py` (MCP stdio transport).
- [ ] **Chunk 17** — Dockerfile + docker-compose + pre-commit hook (ruff + pytest).
- [ ] **Chunk 18** — Remaining 4–7 example briefs (target 5–10 total, distinct industries).
- [ ] **Chunk 19** — Final README + ARCHITECTURE pass.
