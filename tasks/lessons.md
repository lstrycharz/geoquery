# Lessons

Captured corrections during the build. Each lesson traces to a specific past mistake and prescribes what to do next time.

## Chunk 8 — first real-API run surfaced 4 issues

### 1. Sandbox shells inject empty env vars
**Past mistake:** `Settings()` loaded `anthropic_api_key=""` even though `.env` had the real key. Reason: the Claude Code harness shell exports `ANTHROPIC_API_KEY=""`, which pydantic-settings reads before the `.env` file by default — so the empty shell value won.
**Rule:** for every pydantic-settings model that reads from `.env`, set `SettingsConfigDict(env_ignore_empty=True)`. Empty shell vars are almost never the intent.

### 2. Per-skill `max_output_tokens` must be calibrated to the schema's worst case
**Past mistake:** `define_icp` truncated at 4096 tokens mid-JSON. The Anthropic API surfaced this as an empty `tool_use.input = {}`, which then failed contract validation. The actual stop_reason was `max_tokens` — the model didn't fail, the cap did.
**Rule:** (a) every skill carries its own `max_output_tokens` calibrated to its schema's verbose case (multi-segment ICP needs 8k; SERP analysis can be 4k; scored-25-queries needs 8k). (b) In `Skill._invoke_once`, raise immediately when `response.stop_reason == "max_tokens"` with a message that names the skill and its current cap — don't let an empty tool_use slip into contract validation.

### 3. Models double-encode nested array fields
**Past mistake:** `SerpAnalysis.top_results` came back as a JSON-encoded string instead of a real list. The model occasionally treats a complex nested-array field as a single "value to serialize" rather than a structured field. Pydantic rejected it with `list_type` error.
**Rule:** every contract with a `list[SomeModel]` field gets a `@field_validator(..., mode="before")` calling `_coerce_json_list` (decodes the string if it parses to a list; passes through otherwise). The validator is unobtrusive — it only kicks in for the broken case.

### 4. Model-graded judges should be advisory, not blocking
**Past mistake:** `BuyerRealismJudge` flagged 5/25 borderline-formal queries and failed the eval, which triggered the inner-loop revision. The model produced 25 different but similarly-borderline queries on each retry. After 3 attempts → `RetryExceeded` → entire run aborted.
**Rule:** `Evaluator.blocking: bool` — deterministic shape checks default to `True` (these are absolute correctness gates); model-graded judges default to `False` (their signal is valuable in the log but shouldn't gatekeep). Skill base class splits failures into blocking + advisory; only blocking failures feed the revision header.
