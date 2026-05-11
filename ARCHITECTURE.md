# Architecture

> Per-layer design decisions and the tradeoffs behind them. Each section explains *why* the layer is shaped the way it is, *what* alternatives were rejected, and *where* the seams sit for extension.

The document grows alongside the code — one section lands per chunk so the doc and the implementation stay in sync.

---

## Layer 1 — Skills

(chunk 1) The `Skill` base class (`skills/base.py`) is the central abstraction. Every skill is a deep module with one public method, `.run(inputs) -> SkillResult[OutputT]`. Internally it owns:

- a **prompt template** at `skills/prompts/<name>.md` (markdown, reviewable as a first-class artifact, not a Python string literal),
- a **Pydantic output type** (`output_type` class var) — the JSON schema is passed to Anthropic as the input schema of a forced tool call, so the model is *required* to emit the structured output and the response is parsed directly into the contract,
- a **model choice** (`model` class var) — per-skill, because the GEO Query Generator's source specification declares fast-model use *non-negotiable* for buyer realism; per-skill routing is correctness, not optimization,
- a hook for **evaluators** (added in chunk 6) and a revision loop on eval failure.

The base class also threads the `RunBudget` through every call — every skill records cost and increments the per-skill attempt counter before doing any work.

**Why deep modules.** Per Ousterhout: shallow modules (many tiny exports, sprawling cross-dependencies) make every change require walking the dependency graph. A skill has one public surface; the prompt, the parsing, the cost accounting, the eval hooks are all internal. A caller can use it from `agent.py` by reading `Skill.run`'s signature alone.

**Rejected alternative: a single mega-prompt that does the whole pipeline.** That's where most "agents" are today. The cost is that you can't test, evaluate, or swap any step independently — every change is a global change. The decomposition itself is the value.

---

## Layer 2 — Tools

(landing in chunks 4, 10, 11, 12, 16) External, deterministic interfaces. The skills *call* these; they don't reason. SQLite logging is deliberately not in this layer — it's internal infrastructure (memory). The Tools layer is reserved for things that talk to the outside world.

---

## Layer 2.5 — SDK Patterns

(chunk 1) Two transversal patterns the base class enforces on every skill:

- **Structured outputs via forced tool use.** The Anthropic Messages API doesn't have a first-class JSON mode, but it does have forced tool_choice. We pass the Pydantic schema as the tool's `input_schema` and force `tool_choice = {"type": "tool", "name": "emit_<skill>"}`. The model returns the answer as that tool call's input, which we parse directly. This kills an entire class of "the model returned malformed Markdown" bugs.
- **Prompt caching on the static system prompt.** Every skill's `system_prompt` is wrapped with `cache_control: ephemeral`. The dynamic per-call data (company, market, prior outputs) goes in the user message, which is *not* cached. After the first run-per-day, ~80% of system-prompt tokens are read from cache.

---

## Layer 3 — Evals

(landing chunks 6 + 13) Three classes — deterministic (pure Python checks), model-graded (Haiku judges), and golden regression (curated inputs + expected themes, run by `geoquery eval-golden`). Each `Skill` owns its evaluators list; there's no central router — the base class calls `evaluate()` after `run()`.

---

## Layer 4 — Guardrails

(chunk 1) One `RunBudget` object owns both caps:

- **Cost cap.** Each LLM/tool call increments running spend. Before each call, the skill calls `budget.check_can_spend(projected)`; if `spent + projected > MAX_COST_USD`, `BudgetExceeded` is raised and the run aborts cleanly with partial-spend logged to episodic memory.
- **Retry cap.** `budget.register_attempt(skill_name)` increments a per-skill counter; the fourth attempt raises `RetryExceeded`.

**Why one object.** Cost and retry are conceptually the same thing: bounds on a running budget. A single dataclass passed by reference is simpler than two singletons that have to be kept in sync.

---

## Layer 5 — Memory

(chunk 1 = episodic; chunk 7 = semantic) Episodic is a SQLite write log of every run and every skill invocation. Tables carry `schema_version` so old rows stay parseable across contract evolution. Semantic (chunk 7) is `sqlite-vec` + `fastembed` (CPU ONNX, ~50MB, no torch) — past briefs and human-edit angle preferences are retrieved as RAG context for the drafter.

**Why `fastembed` over `sentence-transformers`.** Same vector-DB learning value, dramatically smaller install. No torch dependency.

---

## Layer 6 — Feedback

(chunks 6 + 14) Two loops:

- **Inner loop (sync, chunk 6):** eval fail → re-run the skill with a `[REVISION ATTEMPT n/3]` header prepended to the system prompt that names the specific failure. Bounded by the retry cap.
- **Outer loop (async, chunk 14):** `geoquery feedback <run-id> --edited path.md` is its own subcommand. The user runs it whenever they're done editing — it never blocks the original run. The diff is captured into `human_edits` and the new angle is embedded into semantic memory as a preferred-angle signal for future similar markets.

**Why async outer loop.** Mid-run "press Enter to continue" UX is bad. A separate subcommand decouples the agent's runtime from the human's reviewing rhythm.

---

## Interfaces

(chunks 1 + 16) Two surfaces on the same orchestrator:

- **CLI** (`cli.py`, Typer) — `brief`, `runs`, `show`, `feedback`, `eval`, `eval-golden`.
- **MCP server** (`mcp_server.py`) — exposes `generate_brief` via stdio transport so the agent is callable from Claude Code, Claude Desktop, or any MCP client.

Same `agent.run_brief()` under the hood. MCP is a thin transport layer.

---

## Decision log

A running list of "X over Y, because …" calls made during the build.

- **Sonnet for define_icp, Haiku for generate_geo_query_list** — buyer realism beats strategic depth for the query step (per the source skill's explicit warning).
- **Forced tool_use for structured outputs** — eliminates markdown parsing.
- **`fastembed` over `sentence-transformers`** — same teaching value, no torch.
- **One `RunBudget` over separate cost/retry modules** — they're conceptually one thing.
- **Async outer-loop subcommand over mid-run "press Enter"** — decouples agent runtime from human review.
- **DataForSEO as hybrid (revised)** — the agent runs end-to-end with only `ANTHROPIC_API_KEY` set; `score_queries` falls back to LLM-estimated metrics (`KeywordMetrics.volume = None`). When `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` are set, `tools/dataforseo.py` fetches real volume + KD + CPC + SERP features and `score_queries` consumes them. This preserves cloneability (the "people can read AND extend it" goal) while still showcasing the real-Tool boundary when the key is present. (Earlier draft had DataForSEO as a hard requirement; flipped after the cloneability cost outweighed the teaching clarity.)
- **Blocking vs advisory evals** (chunk 8, lesson from first real-API run) — deterministic shape checks block the pipeline and feed the revision loop; model-graded judges are advisory by default. Reason: in real runs the buyer-realism judge flagged 5/25 borderline queries and blocked the whole pipeline through 3 attempts. The judge's signal was *useful* (those queries WERE slightly over-formal) but not load-bearing for the deliverable. Splitting into blocking/advisory keeps judges' value (surfaced in the episodic log under `[ADVISORY]`) without making them brittle gatekeepers.
- **`env_ignore_empty=True`** (chunk 8 fix) — the harness sandbox shell injects `ANTHROPIC_API_KEY=""` (empty), which by default shadows the `.env` file's value. Setting `env_ignore_empty=True` in `SettingsConfigDict` treats empty shell vars as unset, so the `.env` value loads correctly. Without this, the agent was loading an empty API key while everything looked plumbed.
- **Per-skill `max_output_tokens`** — the first real-API run truncated `define_icp` mid-JSON at 4096 tokens. Each skill now declares its own `max_output_tokens` calibrated to its expected output size; the base class raises a clear error on `stop_reason == "max_tokens"` rather than letting an empty `tool_use` slip through as a contract-validation failure.
- **`_coerce_json_list` defensive validator** — Sonnet occasionally returns nested array fields (e.g. `top_results: list[SerpResult]`) as JSON-encoded strings instead of real lists. A `mode="before"` field validator on every list-of-objects field coerces the string back into a list before Pydantic validates. The contract stays strict; the validator just absorbs a known model quirk.
