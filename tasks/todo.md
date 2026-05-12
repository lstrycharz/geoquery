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
- [x] **Chunk 9** — `research_company` (Sonnet, 11-section CASINO dossier) runs first; `define_icp` consumes it as upstream grounding. Pydantic `_coerce_json_dict` validator added for SWOT/Porter dict fields (parallel to `_coerce_json_list`). 53/53 green.
- [x] **Chunk 10** — `tools/web_fetch.py` (SSRF-hardened: DNS-resolution check, scheme whitelist, redirect re-validation, 5MB streaming cap, 10s timeout). `agent.py` fetches top-3 SERP pages and populates `SerpResult.extracted_content`. analyze_serp prompt updated to consume page content when present. 62/62 green.
- [x] **Chunk 11** — `tools/dataforseo.py` (hybrid; returns {} without creds, uses Labs API when set) → `score_queries` receives `keyword_metrics` and copies real volume/KD/CPC into each `ScoredQuery.metrics`. 67/67 green. Competitor URLs intentionally deferred (would require 25 SERP calls; current `web_search` for the priority query is sufficient).
- [x] **Chunk 12** — `tools/sitemap_parser.py` (SSRF-hardened, supports `<urlset>` + `<sitemapindex>` recursion, caps at 500). CLI gains `--sitemap URL`. Drafter prompt picks 3-5 real URLs from the sitemap with anchors + placement rationale; leaves the section empty when no sitemap is supplied. 73/73 green.
- [x] **Chunk 13** — Golden regression set (3 curated inputs in `tests/golden/inputs.json`) + `geoquery eval-golden [--report]` command. Haiku-based judge checks ICP role keywords + brief angle keywords (60% threshold). `--report` writes a self-contained HTML report to `eval_reports/<timestamp>.html`. Exits non-zero if pass rate < 80%. 77/77 green.
- [x] **Chunk 14** — `geoquery feedback <run-id> --edited path.md` subcommand. Async outer loop: diffs the edited brief against the original, captures the unified diff into `human_edits`, and (if the Angle line changed) re-embeds the new angle into semantic memory so future similar runs surface it via RAG. 81/81 green.
- [x] **Chunk 15** — Streaming + progress events. `agent.run_brief` takes `on_progress`; CLI passes a stderr echo so the user sees `→ skill / ✓ cost` per stage. `DraftContentBrief.streams = True` switches the drafter to `messages.stream()`, calling `progress_callback(chars_streamed)` per delta. Fake test client gained a minimal `stream()` context. 82/82 green.
- [x] **Chunk 16** — `mcp_server.py` exposes `generate_brief(company, market, sitemap?)` over MCP stdio (FastMCP). Same `run_brief` under the hood. Configure Claude Desktop / Code via `claude_desktop_config.json` — example in module docstring. 84/84 green.
- [x] **Chunk 17** — Dockerfile (python:3.13-slim, bakes the fastembed model in for fast first-run) + docker-compose (mounts ./briefs and ./data, .env passthrough) + `.pre-commit-config.yaml` (ruff check + ruff format + pytest). One-time `ruff format .` pass cleaned 11 files. 84/84 still green.
- [x] **Chunk 18** — 5 more example briefs generated (Stripe / Webflow / HubSpot / Vercel / Patagonia), 8 total across B2B SaaS, fintech, no-code, frontend cloud, DTC beauty, DTC outdoor. Total real-API spend: $3.85. Fixed `analyze_serp` token cap (4k → 6k now that page content lands in the prompt) + hardened `_coerce_json_dict/list` to tolerate model wrappers like `dict({...})`.
- [x] **Chunk 19** — Final pass on README (live progress demo block + 8-brief table + Docker quickstart + MCP setup) and ARCHITECTURE (full per-layer write-ups + decision log with every architecturally significant call). 84/84 still green, ruff clean + formatted.

---

**v1.0 ships.** 19 chunks, 19 commits + 1 doc-only DataForSEO flip, 84 tests, 8 example briefs ($3.85 spent), 6 architectural layers populated end-to-end.

---

# v2: Eval Framework — Production-Grade Trust Layer

Plan: see `/Users/lukaszstrycharz/.claude/plans/here-is-a-new-synchronous-wirth.md` (v2 section).

## Vertical slice
- [x] **Chunk 1 — Tracer bullet (eval framework).** Extracted 2 inline judge prompts to `evals/rubrics/{buyer_realism,brief_specificity}.md`; added `evals/rubric_loader.py` (deep module, single `load_rubric` API, KeyError on missing placeholder); added `BrandVoiceMatchJudge` + `brand_voice_match.md` rubric, wired into `DraftContentBrief.make_evaluators(inputs)` when dossier is present (drafter now takes optional `company_dossier`, threaded through `agent.py`); changed `Skill.make_evaluators` signature `()` → `(inputs)` across 6 skill overrides + 3 test monkeypatches; built `dashboard/data.py::recent_runs()` (parameterized SQL, no Streamlit imports) + `dashboard/app.py` Streamlit entrypoint with env-overridable DB path; added `dashboard` extra to `pyproject.toml` (streamlit==1.40.2, pandas==2.2.3); seeded `EVALS.md` with the four-layer overview + rubric catalog. 100/100 tests green (84 v1 + 5 rubric_loader + 3 brand_voice + 5 dashboard_data + 3 e2e cassette unchanged in count).
- [ ] **Chunk 2** — judges #4 (`SearchIntentAlignmentJudge`) and #5 (`BriefActionabilityJudge`) with rubric files + cassette tests.
- [ ] **Chunk 3** — Regression scaffolding (smoke tier): 5 cases in `regression_dataset/`, `evals/regression.py` with `RegressionCassetteClient` keyed by sha256(sys_prompt + user_msg + model) + `RegressionStaleCassetteError`, `pytest -m regression_smoke` for pre-commit.

## Stretches (additive, no v1 regression)
- [ ] **Chunk 4** — Expand regression to 30+ cases (full tier).
- [ ] **Chunk 5** — GitHub Actions regression gate (PR CI + pre-commit hook).
- [ ] **Chunk 6** — Streamlit dashboard full: Evals / Drift / Costs / Tools / Review_Queue pages.
- [ ] **Chunk 7** — Production sample stream + `human_reviews` table.
- [ ] **Chunk 8** — Drift detection + alerts + regression-gate demo (force composite=5.0 → CI fails → GIF).
- [ ] **Chunk 9** — Final EVALS.md + Streamlit Cloud deploy + LinkedIn post draft.
