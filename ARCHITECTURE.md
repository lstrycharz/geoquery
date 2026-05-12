# Architecture

> Per-layer design decisions and the tradeoffs behind them. Each section explains *why* the layer is shaped the way it is, *what* alternatives were rejected, and *where* the seams sit for extension.

The document was written incrementally — one section per chunk — so that the doc and the code stay in sync. The full decision log at the bottom records every architecturally significant call.

---

## Layer 1 — Skills

The `Skill` base class (`skills/base.py`) is the central abstraction. Every skill is a deep module with one public method, `.run(inputs) -> SkillResult[OutputT]`. Internally it owns:

- a **prompt template** at `skills/prompts/<name>.md` (markdown, reviewable as a first-class artifact, not a Python string literal),
- a **Pydantic output type** (`output_type` class var) — the JSON schema is passed to Anthropic as the input schema of a forced tool call, so the model is *required* to emit the structured output and the response is parsed directly into the contract,
- a **model choice** (`model` class var) — per-skill, because the GEO Query Generator's source specification declares fast-model use *non-negotiable* for buyer realism; per-skill routing is correctness, not optimization,
- a **per-skill `max_output_tokens`** sized to the expected verbose output (8k for the multi-segment ICP, 6k for the brief drafter, 4k for SERP analysis, etc.) — the base class raises a clear error on `stop_reason == "max_tokens"` rather than letting an empty `tool_use` slip through as a contract failure,
- a list of **evaluators** returned by `make_evaluators()` — chunked into blocking (revision-loop) and advisory (log-only).

The base class also threads the `RunBudget` through every call — every skill records cost and increments the per-skill attempt counter before doing any work.

**Why deep modules.** Per Ousterhout: shallow modules (many tiny exports, sprawling cross-dependencies) make every change require walking the dependency graph. A skill has one public surface; the prompt, the parsing, the cost accounting, the eval hooks are all internal. A caller can use it from `agent.py` by reading `Skill.run`'s signature alone.

**Rejected alternative: a single mega-prompt that does the whole pipeline.** That's where most "agents" are today. The cost is that you can't test, evaluate, or swap any step independently — every change is a global change. The decomposition itself is the value.

### The seven skills

| Skill | Model | Output | Why this model |
|---|---|---|---|
| `research_company` | Sonnet 4.6 | `CompanyDossier` (11 CASINO sections) | Synthesis from sparse public surface |
| `define_icp` | Sonnet 4.6 | `ICPSegmentList` (2–4 segments) | Strategic firmographic + persona reasoning |
| `generate_geo_query_list` | **Haiku 4.5** | `BuyerJourney` (25 queries, 5 framings) | **Non-negotiable** per source skill — thinking models over-reason and produce SEO-pro queries instead of buyer-realistic ones |
| `score_queries` | Sonnet 4.6 | `ScoredQueryList` (one ScoredQuery per query) | Combines DataForSEO metrics with qualitative judgment |
| `select_priority_query` | Sonnet 4.6 | `Priority` | Strategic tie-break, not pure argmax |
| `analyze_serp` | Sonnet 4.6 | `SerpAnalysis` (top-10 + common angles + content gaps) | Synthesizes across fetched pages |
| `draft_content_brief` | Sonnet 4.6 (streaming) | `ContentBrief` | Long-form structure; streams to stderr for live UX |

---

## Layer 2 — Tools

External, deterministic interfaces. The skills *call* these; they don't reason. SQLite logging is deliberately not in this layer — it's internal infrastructure (memory). Tools is reserved for things that talk to the outside world.

### The five tools

- **`web_search`** — wraps Anthropic's native `web_search_20250305` server tool behind a deterministic function returning `list[SerpResult]`. The model chooses when to issue searches; we force a final `emit_serp_results` tool call to extract structured output. Charges ~$0.01 per call (Anthropic's per-search pricing) to the `RunBudget`.
- **`web_fetch`** (SSRF-hardened) — fetches one page and returns readability-extracted body text or `None`. Hardening:
  - scheme whitelist (http/https only)
  - DNS-resolution SSRF check rejects private/loopback/link-local/reserved/multicast IPs
  - redirect follow disabled; each hop re-validates through the same SSRF check (max 1 redirect)
  - streaming response with 5MB size cap; 10s end-to-end timeout
- **`dataforseo`** (hybrid) — when `DATAFORSEO_LOGIN`/`PASSWORD` are set, fetches search volume + KD + CPC + SERP features via the Labs API (two batched calls per run, ~$0.10 total). When absent, returns `{}` and `score_queries` falls back to LLM-estimated metrics. The agent runs end-to-end either way.
- **`sitemap_parser`** — fetches and parses an XML sitemap (supports `<urlset>` + `<sitemapindex>` with one level of recursion). Caps at 500 URLs; SSRF-hardened (reuses `web_fetch._is_safe_url`); XML parser has external-entity resolution disabled.
- **`slack_notify`** — POSTs to `SLACK_WEBHOOK_URL` if set; no-ops + logs otherwise. Real implementation, not a stub.

---

## Layer 2.5 — SDK Patterns (transversal)

Two patterns the `Skill` base class enforces on every skill:

- **Structured outputs via forced tool use.** The Anthropic Messages API doesn't have a first-class JSON mode, but it does have forced `tool_choice`. We pass the Pydantic schema as the tool's `input_schema` and force `tool_choice = {"type": "tool", "name": "emit_<skill>"}`. The model returns the answer as that tool call's input, which we parse directly. This kills an entire class of "the model returned malformed Markdown" bugs.
- **Prompt caching on the static system prompt.** Every skill's `system_prompt` is wrapped with `cache_control: ephemeral`. The dynamic per-call data (company, market, prior outputs) goes in the user message, which is *not* cached. After the first run-per-day, ~80% of system-prompt tokens are read from cache.

Bonus pattern for one skill: **streaming**. `DraftContentBrief.streams = True` switches `_invoke_once` from `messages.create()` to `messages.stream()` and emits partial-JSON char counts to `progress_callback` per delta event. The CLI wires the callback to `typer.echo(err=True)` so the user sees the brief assembling in real time.

---

## Layer 3 — Evals

Each `Skill` owns its evaluators by overriding `make_evaluators()`. There's no central router — the base class calls `evaluate()` after `run()` and routes failures into a revision feedback loop.

Three evaluator classes:

- **Deterministic** (`evals/deterministic.py`, pure functions) — shape checks that Pydantic alone can't enforce:
  - dossier has all 11 CASINO sections non-empty
  - ICP has 2–4 segments; each has language_patterns + decision_criteria + strategic_pain_points
  - query list has 22–28 items; `refinement_applied` matches positions 1–14 vs 15+
  - scored queries have valid composites in [1, 10] and non-empty rationales
  - SERP analysis has non-empty common_angles + content_gaps + recommended_format
  - brief structure is non-empty per section; angle ≥ 6 words; sources non-empty
- **Model-graded** (`evals/model_graded.py`, Haiku-based judges):
  - `BuyerRealismJudge` — catches the source GEO Query Generator's named anti-pattern (expert-toned queries). Threshold: ≥70% must read as real buyers.
  - `BriefSpecificityJudge` — catches generic briefs that read like "best knowledge management tools".
- **Golden regression** (`evals/golden_set.py`) — 3 curated `(company, market, expected_themes)` inputs (extensible). Run via `geoquery eval-golden` with real LLM calls. Haiku judge checks ICP role keywords + brief angle keywords at 60% threshold. `--report` writes a static HTML page.

### Blocking vs advisory

`Evaluator.blocking: bool` — deterministic checks default to `True` (absolute correctness gates); model-graded judges default to `False` (their signal is valuable in the log but shouldn't gatekeep). The base class splits failures into `blocking_failures` (feed the revision header) and `advisory_failures` (log with `[ADVISORY]` prefix). This came out of the first real-API run, where the buyer-realism judge correctly flagged 5/25 borderline queries and blocked the whole pipeline through 3 retries — useful signal, wrong place to enforce it.

---

## Layer 4 — Guardrails

One `RunBudget` object in `guardrails/limits.py` owns both caps:

- **Cost cap.** Each LLM/tool call increments running spend. Before each call, the skill calls `budget.check_can_spend(projected)`; if `spent + projected > MAX_COST_USD`, `BudgetExceeded` raises and the run aborts cleanly with partial-spend logged to episodic memory.
- **Retry cap.** `budget.register_attempt(skill_name)` increments a per-skill counter; the fourth attempt raises `RetryExceeded`.

**Why one object.** Cost and retry are conceptually the same thing: bounds on a running budget. A single dataclass passed by reference is simpler than two singletons that have to be kept in sync.

Default cap: `$3` per run. Calibrated empirically — happy path runs ~$0.30 (v1 path) to ~$0.60 (full path with `research_company` + DataForSEO). $3 trips on actual runaway revisions without false-alarming healthy runs.

---

## Layer 5 — Memory

### Episodic (`memory/episodic.py`)

SQLite write log of every run and every skill invocation. Append-only, parameterized writes, schema-versioned rows. Tables:

- `runs` (id, started_at/ended_at, company, market, status, total_cost_usd, brief_path)
- `skill_invocations` (run_id, skill_name, attempt, model, input_json, output_json, eval_passed, eval_details_json, tokens, cost, duration_ms)
- `human_edits` (run_id, original_brief_path, edited_brief_path, diff_summary, captured_at) — populated by `geoquery feedback`.

Every row carries `schema_version: 1` so contract evolution doesn't break old data.

### Semantic (`memory/semantic.py`)

`sqlite-vec` virtual table (`vec0`, 384-dim) + `fastembed` with `BAAI/bge-small-en-v1.5` (CPU ONNX, ~50MB, no torch dependency). One row per past brief, indexed on the signature `(market + icp_summary + angle)`.

On a new run, after `define_icp` chooses the primary segment, the drafter retrieves the top-3 nearest past briefs and injects them into its user message with explicit "do NOT repeat these angles — differentiate" framing. The RAG context steers the model *away* from prior work, not toward it.

When the outer feedback loop captures a human edit, the new preferred angle gets indexed too — under run_id `<original-run>::edited` — so future similar runs surface it.

**Why fastembed over sentence-transformers.** Same vector-DB learning value, dramatically smaller install. No torch.

**SQLite extension-loading gotcha.** macOS pyenv-built Python lacks `enable_load_extension`. Brew Python 3.13+ has it; the Docker image (Debian-based) has it. Documented in README.

---

## Layer 6 — Feedback

Two loops:

- **Inner loop (sync).** Eval fail → re-run the skill with a `[REVISION ATTEMPT n]` header prepended to the system prompt:

  ```
  [REVISION ATTEMPT 2]
  The previous output failed these checks:
  - [icp_segments_in_range] need 2-4 segments, got 1
  Re-do the task, addressing each failure specifically.
  ---
  <original system prompt>
  ```

  The revision header is a *separate, non-cached* content block, so the original cached system prompt stays warm. Bounded by `RunBudget.register_attempt`'s retry cap (3 attempts).

- **Outer loop (async).** `geoquery feedback <run-id> --edited path.md` is its own subcommand. Never blocks the original run. It diffs the edited brief against the original (extracted via the episodic log's `brief_path`), captures the unified diff into `human_edits`, and — if the `**Angle:**` line changed materially — re-embeds the new angle into semantic memory with run_id `<original>::edited`.

**Why async outer loop.** Mid-run "press Enter to continue" UX is bad. A separate subcommand decouples the agent's runtime from the human's reviewing rhythm.

---

## Interfaces

Two surfaces on the same `agent.run_brief()`:

- **CLI** (`cli.py`, Typer):
  - `geoquery brief --company X --market Y [--sitemap URL]` — generate a brief, with live progress to stderr
  - `geoquery runs` — list past runs
  - `geoquery show <run-id>` — run metadata + skill invocations
  - `geoquery feedback <run-id> --edited path.md` — outer-loop capture
  - `geoquery eval-golden [--report]` — regression set; exits non-zero if pass rate <80%
- **MCP server** (`mcp_server.py`, FastMCP) — exposes `generate_brief(company, market, sitemap?)` over stdio. Configure Claude Desktop's `claude_desktop_config.json` to point at it. Same orchestrator under the hood — MCP is a thin transport layer.

---

## Test discipline

- **Cassette-driven unit tests** for every skill + tool. The fake Anthropic client (`tests/conftest.py`) parses a forced-tool-use cassette and returns it as the API response. Fast (<3 s for 84 tests), deterministic, $0 LLM cost.
- **Golden regression set** for real-LLM verification. Run via `geoquery eval-golden` when prompts change.
- **TDD note:** TDD applies to code (parsing, retry, memory writes, tool wrappers, guardrails, CLI plumbing). Prompts are a different artifact and are tested via (a) Pydantic structured-output parsing (a malformed response fails fast), (b) cassette replays, and (c) the golden set. Each chunk's commit message records the TDD-style red→green→refactor cycle for code; prompt changes are gated by the golden set's pass rate.

---

## Decision log

A running list of "X over Y, because …" calls made during the build.

- **Sonnet for define_icp, Haiku for generate_geo_query_list** — buyer realism beats strategic depth for the query step (per the source skill's explicit warning).
- **Forced tool_use for structured outputs** — eliminates markdown parsing.
- **`fastembed` over `sentence-transformers`** — same teaching value, no torch.
- **One `RunBudget` over separate cost/retry modules** — they're conceptually one thing.
- **Async outer-loop subcommand over mid-run "press Enter"** — decouples agent runtime from human review.
- **DataForSEO as hybrid (revised)** — the agent runs end-to-end with only `ANTHROPIC_API_KEY` set; `score_queries` falls back to LLM-estimated metrics. When credentials are set, `tools/dataforseo.py` fetches real volume + KD + CPC + SERP features and `score_queries` consumes them. (Earlier draft had DataForSEO as a hard requirement; flipped after the cloneability cost outweighed the teaching clarity.)
- **Blocking vs advisory evals** (chunk 8, lesson from first real-API run) — deterministic shape checks block the pipeline and feed the revision loop; model-graded judges are advisory by default. Reason: the buyer-realism judge flagged 5/25 borderline queries and blocked the whole pipeline through 3 attempts. Useful signal, wrong place to gatekeep.
- **`env_ignore_empty=True`** (chunk 8 fix) — sandbox shells (e.g. Claude Code's harness) inject `ANTHROPIC_API_KEY=""` which by default shadows the `.env` file. Setting `env_ignore_empty=True` in `SettingsConfigDict` treats empty shell vars as unset.
- **Per-skill `max_output_tokens`** — the first real run truncated `define_icp` mid-JSON at 4096 tokens. Each skill now declares its own cap calibrated to its schema's verbose case; the base raises a clear error on `stop_reason == "max_tokens"`.
- **`_coerce_json_list` / `_coerce_json_dict` defensive validators** — Sonnet occasionally returns nested array/dict fields as JSON-encoded strings (sometimes wrapped, like `dict({...})`). `mode="before"` field validators decode strings and extract bracketed substrings on `JSONDecodeError`. The contract stays strict; the validator absorbs known model quirks.
- **Streaming on the drafter only** — token-level UX feedback is most valuable on the longest-running skill. Other skills emit progress at boundaries only. Avoids the complexity of streaming partial JSON for every skill.
- **Sitemap-grounded internal linking, optional** — when `--sitemap` is supplied, the drafter picks 3–5 real URLs with anchors. When absent, leaves the section empty — *never* invents URLs. Anti-hallucination via prompt rule.
- **Skill base class enforces structured outputs + prompt caching universally** — eliminates per-skill boilerplate; every skill gets these for free. Net effect: ~30 LOC per skill module instead of ~120.
