# Agent / LLM-Pipeline Project Playbook

A planning aid for any new AI-agent or LLM-pipeline project, distilled from
building GEOQuery (v1 → v2 → v3). The companion rule that points back here
lives at `~/.claude/rules/agent-design.md`.

The rest of this repo is the **worked example** — every principle below is
implemented somewhere; file pointers in `[brackets]` show you where.

---

## How to use this

Walk this document **in plan mode at project kickoff**, in order. Decide
which layers apply (most projects: 1; many: 1+2; few: 1+2+3). Mark the
non-applicable sections "n/a, because …" — that recorded reasoning is
itself useful when scope changes later.

Apply in order. **Never skip 1 or 2 to reach 3.** Layer 3 without Layer 2
is reward hacking with extra steps; Layer 2 without Layer 1 is testing a
black box.

---

## When this framework applies

| Apply when… | Skip when… |
|---|---|
| Multi-step LLM work — research → plan → produce → review | A single LLM call inside a feature |
| Will be **shipped or iterated** over weeks/months | One-shot script, demo, or proof-of-concept |
| Output quality matters and you need to **prove** it does | "Good enough if it sometimes works" |
| You'll be the one fixing the regression at 3am | Throwaway internal automation no one depends on |

If the project doesn't pass at least two of the "apply when…" rows, stop —
you're over-engineering. A 50-line LangChain script is fine.

---

## The three layers at a glance

| Layer | What it gets you | Typical cost to build | Apply when |
|---|---|---|---|
| **1. Decomposition** | A debuggable, inspectable agent with named failure modes | 1–3 weeks | Every agent project |
| **2. Evaluation discipline** | A regression gate and a calibrated trust signal | +1–2 weeks on top of L1 | You'll ship/iterate it |
| **3. Self-improvement** | A system that learns from its track record and can propose its own changes | +2–3 weeks on top of L2 | Long-lived agent with enough trace history to learn from — and the appetite for the reward-hacking defense |

---

# Layer 1 — Decomposition

**Goal:** turn one big "AI does the job" black box into 5–9 named stages,
each of which you can read, test, and improve without breaking the others.

## L1.1 — Identify the stages

Ask: *what would a human expert do, step by step, to produce this output?*
Write those steps down. Aim for **5–9 stages** — fewer and you're under-
decomposing; more and you've split too fine.

For each stage, name:
- **One job.** If you can't state it in one sentence, split it.
- **What it takes in** (typed).
- **What it produces** (typed).
- **Whether it needs the outside world** (web, API, database) — that
  determines whether a *Tool* (Layer 2 of the architecture) sits between
  the stage and the world.

Reference: GEOQuery's seven stages — `agent.py`, `skills/*.py`,
[`ARCHITECTURE.md`](../ARCHITECTURE.md).

## L1.2 — Each stage is a deep module

A **deep module** has a small public interface and hides a lot of
complexity — the principle from Ousterhout's *A Philosophy of Software
Design*, applied directly. AI codebases default to the opposite ("classitis":
one class to format the prompt, one to call the model, one to parse the
JSON), which produces high cognitive load with no information hiding.

- ✅ One public method: `run(inputs) -> output`.
- ✅ Inside: prompt + strict output contract + model choice + own evaluators.
- ❌ Don't export the prompt, the parser, the retry logic, the cost-tracking
  separately. The next caller doesn't care.
- ❌ Don't extract every helper into its own file because "reusable." If
  there's no second caller yet, it's speculative.

**The test:** can a caller use this stage by reading just its public
interface, or do they need to walk five other files? If five files, the
module is leaky — collapse the helpers back in.

Reference: `skills/base.py::Skill` + any `skills/<name>.py`.

## L1.3 — Strict output contracts

Every stage's output is a **strict typed shape**. Pydantic in Python, Zod
in TS, whatever.

- ✅ **Force the schema at the API level**, not just in-prompt instructions:
  OpenAI's `response_format={"type":"json_schema",...}`, or Anthropic's
  forced tool calling (`tool_choice={"type":"tool","name":...}` with the
  schema as the tool's `input_schema`). The model literally cannot return
  malformed JSON. *Asking* a model to return JSON in prose is obsolete.
- ✅ Malformed output **fails loudly and immediately** — not three stages
  later as a `'NoneType' has no attribute …`.
- ✅ Validators that gently coerce common model quirks (e.g. the model
  occasionally returns a list as a JSON string — a `_coerce_json_list`
  validator). Be defensive about *known* model quirks, strict about
  everything else.
- ❌ "Parse the model output with regex." Always loses.

Reference: GEOQuery `skills/base.py` (every skill call goes through Anthropic
forced tool-use with a Pydantic-derived `input_schema`) + `contracts.py`
(the `_coerce_json_list` / `_coerce_json_dict` validators are documented
battle scars).

## L1.4 — Per-stage model routing as *correctness*

The most counterintuitive lesson: **the right model for a stage isn't
always the most powerful one.** Stronger "thinking" models over-reason on
some tasks; the faster, lighter model gets closer to ground truth.

Examples:
- **Brainstorming what a real buyer would search for** — Haiku, on
  purpose. Sonnet/Opus produce expert-sounding queries no real human
  types. (GEOQuery, `generate_geo_query_list`.)
- **Strategic synthesis** (research, framing, judgment) — Sonnet.
- **Outcome prediction / second-opinion judging** — Opus. Worth the cost
  because it runs rarely.

For each stage, write down *why* you picked the model. "Default Sonnet"
isn't an answer — name the property of the task that makes that model
right.

## L1.5 — Tools as the boundary

Anything that hits the outside world (web, APIs, databases, the file
system) is a **Tool**, kept strictly separate from reasoning code.

Why: the model can't reason its way to a search result or a database row.
Tools are the deterministic bridge. Keeping them separate makes them:
- mockable in tests (cassettes, fakes);
- security-auditable (SSRF on web fetchers, parameterized SQL);
- replaceable (swap DataForSEO for a different keyword API in one place).

Tool design rules:
- **Total functions** — never raise on a failure the agent could
  reasonably continue past. Return `{}` or `None` and let the caller
  decide. (GEOQuery's `tools/dataforseo.py` returns `{}` on bad creds; the
  agent falls back to LLM estimates.)
- **Security-harden anything fetching arbitrary URLs** — DNS-resolution
  check, scheme allowlist, redirect re-validation, size cap, timeout.
- **Parameterized DB queries.** Always. No exceptions.

## L1.6 — Guardrails up front, not last

Two things, threaded through every run from day one:

- **Cost cap** — projected next call + spent > cap → abort cleanly before
  spending. Don't ship "we'll add this later," you won't.
- **Retry cap** — every stage at most N attempts (3 is sane). On exhaustion,
  abort with a clear, recorded reason — not an infinite loop.

Reference: `guardrails/limits.py::RunBudget`.

## L1.7 — Two interfaces are usually right

Most agent projects benefit from **two surfaces** sharing one orchestrator:
- A CLI (you and your team's daily tool).
- An MCP server, HTTP service, or library entry point (so the agent can
  be called from somewhere else — Claude Desktop, a web app, a cron).

Build the orchestrator first; both surfaces are thin shells over it.

Reference: GEOQuery `cli.py` + `mcp_server.py`, both calling `agent.run_brief`.

---

# Layer 2 — Evaluation discipline

**Goal:** stop guessing whether the agent works. Build the machinery to
*prove* it does, catch regressions before they ship, and keep AI judges
calibrated against humans.

Skip if the project is a one-off. Apply for anything you'll iterate.

## L2.1 — Define "good output" per stage

For each stage, write down — in **plain English** — what makes its output
good or bad. Then split that list into:

- **Deterministic checks** — things a Python function can verify (shape,
  count, presence, format, value ranges).
- **Judgment calls** — things only a reader (human or LLM) can verify
  (does the angle name a specific persona pain? is the language concrete?).

Both are evaluators. They live next to the stage, attached by the stage.

Reference: `evals/deterministic.py` (pure functions) + `evals/model_graded.py`
(Haiku judges) + `evals/rubrics/*.md` (the judges' instructions in plain
English so PR diffs read like prose).

## L2.2 — Blocking vs advisory

Every evaluator carries a `blocking: bool`.

- **Blocking** failure → forces a stage re-run (revision loop). Use for
  deterministic shape/count checks.
- **Advisory** failure → logged, surfaced in the dashboard, doesn't gate.
  Use for noisy LLM judges where any single judge call is unreliable.

In a system with multiple judges, **consensus-gate** the advisory ones: a
lone judge failing stays advisory, but a *majority* failing triggers a
revision. Pure-advisory under-reacts (ships work multiple judges flagged);
full re-gate thrashes on one noisy judge call.

If your judges are slow or expensive (Opus-tier reasoning, big payloads),
fire the advisory ones **asynchronously** after the response is returned —
their verdict still lands in the log and dashboard, it just doesn't block
the user. GEOQuery's judges are cheap Haiku calls (<2s, ~$0.001) so
synchronous is fine; pick the right answer for your latency budget.

Reference: `skills/base.py::Skill.run` (the revision loop with
`judge_consensus_threshold`).

## L2.3 — Cassette-replay regression suite

The single highest-leverage piece of testing for any LLM system. (A
**cassette** here is a saved LLM response — the parsed structured output,
not the raw HTTP envelope — replayed in tests instead of calling the real
API. Same idea as VCR.py but at the contract level, not the wire level.)

- Record 30+ representative cases once (real API, real money — budget $10–30).
- Each case = `(input, recorded LLM responses, expected output profile)`.
- Replay deterministically on every PR via CI. **$0, deterministic, runs
  in seconds.**

Cassette-key on **`sha256(system_prompt + user_message + model)`**. Without
prompt-hashing, a prompt edit silently replays the old response and the
gate is theatre. With it, prompt edits force a "stale cassette" failure →
explicit re-record decision.

Two tiers:
- **Smoke** (5 cases, pre-commit, ~10s) — fast feedback locally.
- **Full** (30 cases, PR CI, ~30s) — broader coverage.

Re-record workflow documented and available locally; CI is replay-only.

Reference: GEOQuery `regression_dataset/*` + `evals/regression.py` +
`.github/workflows/regression.yml`.

## L2.4 — CI gate

Wire the regression suite into a CI workflow that runs on every PR.
**Block merge** via branch protection / rulesets until it passes.

This is the unglamorous piece that prevents the most common failure mode:
"the prompt change *looked* fine in the PR diff, and now production briefs
have no internal links."

Demo it once on camera — deliberately break a stage, watch the gate catch
it, fix and watch it pass. That's the trust receipt.

Reference: GEOQuery `.github/workflows/regression.yml`, `docs/regression_gate_demo.md`.

## L2.5 — Production sample stream

10% of completed runs (configurable) get flagged for a **human** to rate.
A small form: 1–5 overall + per-dimension. Persisted.

Then compute **judge-vs-human divergence**: if the AI judges keep saying
"ship it" but humans keep saying "no," the judges need retraining — and
the dashboard surfaces it.

This is what stops the trust layer from drifting silently.

Reference: GEOQuery `evals/production.py::maybe_sample_for_review`,
`dashboard/pages/5_Review_Queue.py`.

## L2.6 — One log, one dashboard

A single append-only SQLite (or equivalent) log of every run, every stage,
every evaluator verdict, every cost, every duration. The dashboard is
read-only over that log.

The log being **single** matters. Don't have a separate audit log and a
metrics log and a cost log — one log, queried different ways. The
dashboard pages are thin presentation over pure query functions in a
testable data module.

Reference: GEOQuery `memory/schema.sql`, `dashboard/data.py` (the pure
query functions are unit-tested).

## L2.7 — Tests cost $0 and run in seconds

If your test suite takes minutes or costs real money to run, fix that
before anything else. A slow/expensive suite gets skipped, then ignored,
then deleted.

The combination of cassettes (Layer 2.3) + stub embedders + stub clients
gets the whole suite to <15s and $0. Aim for that.

---

# Layer 3 — Self-improvement (apply with caution)

**Goal:** the system uses its own track record to make future runs better,
and (optionally) a meta-agent proposes its own changes.

**Apply only if all of these are true:**
- Layer 2 is solid and you have ≥1 month of real run history.
- The agent will keep running long enough that the meta-loop's payoff
  matters (weekly cron → meaningful effect after months).
- You have the appetite to build the reward-hacking defense properly.
  Without it, this layer is actively harmful.

If those aren't all true, **stop at Layer 2**.

## L3.1 — Memory-driven improvement

Two ideas:

**Score-aware retrieval.** Tag every output with a quality score (your
eval composite). When the agent starts a new run on a similar topic, pull
the *highest-scoring* prior outputs as few-shot examples — not the
nearest, the *good ones*. Inject slim (angle + structure, ~200 tokens
each), not full bodies — the few-shot carries shape, not depth.

**Distilled patterns.** Periodically (weekly), an LLM call reads the
top-N highest-scoring outputs and extracts their common structural
patterns ("the great ones name a specific persona pain in the headline").
Cache, inject into the relevant stage as guidance. Periodic, not per-run.

Reference: GEOQuery `memory/semantic.py::find_similar(rank_by_eval_score=True)`,
`evals/winning_patterns.py`.

## L3.2 — Outcome signals: real vs simulated, labelled either way

If you can wire **real outcome data** (search rankings, conversion rates,
whatever) — use it.

If you **can't** but want a proxy, an LLM can play "30-day outcome judge"
on a sample of outputs. **That signal is *simulated* and must be labelled
that way everywhere it appears** — the table comment, the contract
docstring, the prompt itself, the CLI help. Never pretend a proxy is
ground truth.

Mix simulated signals into your composite eval score at a weight that
keeps the real signal dominant (e.g. 0.4). When real data becomes
available, the proxy gets replaced, not augmented.

Reference: GEOQuery `skills/predict_outcome.py`, `SELF_IMPROVEMENT.md`'s
honesty section.

## L3.3 — Inner-loop revision strengthening

On retry-cap exhaustion, don't bare-abort — write a rich **escalation
record**: every attempt's failures + the final rejected output. That
record is the meta-agent's single richest input signal: a clustered
escalation on one stage is a systematic failure worth a proposal.

Reference: GEOQuery `SkillEscalation`, `escalations` table.

## L3.4 — The meta-agent

A weekly cron reads the eval history, identifies one systematic pattern,
proposes one specific fix, opens a PR. A human reviews and merges. After
N post-merge runs, measure whether it helped — auto-revert if it clearly
hurt.

The architecture is **three components, separated**:
1. **`analyze`** — rule-based, **no LLM**, read-only DB. Returns a ranked
   list of patterns. Rule-based on purpose: an LLM picking which pattern
   to "discover" can cherry-pick the easiest one to game.
2. **`propose`** — the single LLM call. Takes one pattern + the actual
   outputs, produces one diff + one hypothesis. See L3.5 for what it must
   NOT see.
3. **`measure`** — post-merge attribution. Honest numbers, no t-test
   theater (sample sizes can't support one). Auto-revert on clear
   regression so the loop closes both ways.

Reference: GEOQuery `meta/{analyze,propose,measure}.py`.

## L3.5 — The reward-hacking defense (non-negotiable)

**This is the actual point of Layer 3.** A meta-agent told to "improve the
eval scores" will, given the chance, weaken a rubric, edit a regression
baseline, add a trivially-passing eval, or push outputs toward verbose
patterns the LLM judges like and humans don't. That failure mode is
**reward hacking** (also called **specification gaming** in the safety
literature — Krakovna et al., DeepMind 2020), and it's the default behavior
of an optimizer pointed at a gameable metric.

> A note on framing: this is **not** RLAIF. RLAIF specifically means using
> AI-generated preference labels to train a reward model that drives
> gradient-based RL fine-tuning. The meta-agent here proposes code/prompt
> edits as pull requests; humans are the merge gate; no weights ever move.
> It's closer in spirit to **automated prompt/program optimization** (DSPy,
> OPRO). The *failure mode* — specification gaming — is the same one
> RLHF/RLAIF systems face, which is why the defenses below are worth as
> much as they are. Borrowing the failure-mode lineage is correct;
> borrowing the technique name is not.

The defense has nine parts. **All of them. None are optional.**

1. **Constrained edit surface.** Deny-by-default. The meta-agent may only
   touch a tiny allowlist (prompt files, rubric tightenings, net-new evals
   in a dedicated subdir). Never the grader code, never the regression
   dataset, never its own allowlist.

2. **The optimizer is blind to the rubric prose** of the judges it's
   optimizing against. It sees the *pattern* (what regressed) and the
   *actual outputs* (the work) — never the grader's text. If it could
   read the rubric, it would optimize against the rubric. Tested
   explicitly.

3. **Multiple independent guards (≥6)** on every proposal:
   - protected-path check (allowlist + rubric-tighten-only),
   - trivial-eval check (new evals must discriminate on a protected corpus),
   - divergence-regression check (judge-vs-human divergence can't rise),
   - cassette-integrity check (regression dataset untouched),
   - verbosity guard (output length can't balloon without a human-rating gain),
   - single-change check (one logical change per proposal).

4. **Guards run from a trusted copy of themselves** — checked out from the
   base ref, never the PR head. A meta-agent that edits its own guards is
   caught by the un-edited guards.

5. **Fingerprints (sha256) of every grader file** stored as a baseline.
   Tamper detection on the grading logic.

6. **Read-only DB handle** for the meta-agent. It can't delete a record to
   manufacture (or hide) a pattern.

7. **Net-new evaluators are human-wired, not auto-discovered.** An
   approved file in the proposed-evals directory does not run
   automatically. A human deliberately wires it in on merge.

8. **Access token is PR-write only.** No merge, no branch-protection
   edit, no push to a protected branch. Humans are always the final gate.

9. **No statistical theater.** Report honest primitives (n, before/after,
   effect size). Flag "underpowered" when n is too small. Faking a t-test
   to look rigorous is the statistical version of the exact reward
   hacking this layer guards against.

**The unifying principle** (Karpathy's `autoresearch` lesson): **lock down
the metric, the data, and the scope — let only the agent's reasoning
vary.** Every defense above is a different way of doing that.

If you don't have the appetite for all nine, **don't ship Layer 3** —
ship Layer 2 and call it a day. Layer 3 done badly is worse than no
Layer 3.

Reference: GEOQuery `meta/`, [`SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

---

# Portable patterns

These transfer to any system that involves AI quality, not just agent
projects:

| Pattern | Why it transfers |
|---|---|
| **Deep modules over shallow** | The Ousterhout principle is correct for any complex system. Test boundaries belong around deep modules, not individual functions. |
| **Structured outputs over regex** | Anywhere a model produces structured data, force a schema. Failure becomes loud and immediate. |
| **Cassette-replay tests over live API in CI** | Anywhere your tests would otherwise call an external service, cassette it. Free, fast, deterministic. |
| **Advisory vs blocking distinction** | In any quality-check system. Forces you to be honest about which signals are reliable enough to gate on. |
| **No statistical theater** | Underpowered is a real answer. Report n; refuse to overclaim. |
| **Honest labelling of proxy/simulated signals** | If a signal isn't ground truth, label it that way everywhere it appears — never let it accumulate the credibility of real data. |

---

# Anti-patterns

- **One giant prompt** trying to do the whole job. Unreviewable, untestable,
  unimprovable.
- **No output contract.** Parsing model output with regex. (You will lose.)
- **Blocking on noisy judges.** Either consensus-gate them or keep them
  advisory.
- **Tests that cost real money in CI.** Cassettes exist.
- **Self-improvement without the reward-hacking defense.** Either build all
  nine guards, or stop at Layer 2.
- **Statistical theater.** A p-value computed on 12 samples is worse than
  saying "underpowered."
- **Pretending a simulated signal is real data.** Costs trust fast, hard
  to recover.

---

# Using this in plan mode

At project kickoff:

1. Read this document end-to-end.
2. Decide which layers apply. Record the "n/a, because…" reasons for any
   you skip.
3. Write the plan (e.g. `tasks/todo.md` per the workflow rules) as
   **vertical slices, not horizontal layers**. The first chunk should be a
   tracer bullet through every applicable layer end-to-end (one stage +
   one eval + one regression case + one CI run).
4. Apply your usual chunk-by-chunk red-green-refactor discipline (see
   `qa.md`).
5. Keep the per-PR CI gate green from chunk 1.
6. When you hit a tradeoff, search this doc for the relevant section —
   the lesson is usually already recorded.

If you need a worked example of any specific pattern, the GEOQuery repo
implements every one. Find the section header, open the linked files,
read the surrounding tests.
