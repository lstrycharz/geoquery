# LinkedIn post draft

Three lengths — pick whichever fits the moment. The short one is the
hook; the medium adds the framework; the long adds proof + a call to
action.

---

## Short (200 chars, the hook)

Your AI agent doesn't have evals? It's a science project, not a system.

Here's what a real eval framework looks like — on a real agent, with a
regression gate that's caught a real bug on camera:

→ github.com/lstrycharz/geoquery

---

## Medium (~800 chars, the framework)

> *Your AI agent doesn't have evals? It's a science project, not a system.*

Most "AI agent" repos are one giant prompt that hopes the model does the
right thing. They work sometimes and break in surprising ways the rest
of the time. You can't trust them at 3am Sunday.

So I built one I can. The eval framework has four layers:

1. **Deterministic** — schema, word counts, required sections. Pure
   functions. Sub-millisecond. Blocking.
2. **LLM-as-judge** — 5 Haiku judges. Each rubric is a Markdown file in
   `evals/rubrics/` so PR diffs read like English, not Python strings.
3. **Regression suite** — 30 cassette-replayed cases keyed by
   `sha256(system_prompt + user_message + model)`. Any prompt change
   forces a stale-cassette miss with a loud diff. Deterministic, $0/run.
4. **Production monitoring** — Streamlit dashboard reading the agent's
   SQLite log. Pass-rate per skill, cost percentiles, 7-day drift,
   judge-vs-human divergence on a 10% production sample.

The regression gate runs on every PR via GitHub Actions. I deliberately
broke `score_queries.composite = 5.0` and watched it catch the
regression in 7 seconds with a PR comment naming the three failed cases.
GIF in the repo.

→ github.com/lstrycharz/geoquery
→ docs/regression_gate_demo.md

---

## Long (~2000 chars, framework + proof)

> *Your AI agent doesn't have evals? It's a science project, not a system.*

Most AI agents I see are one giant prompt that hopes the model does the
right thing. They work sometimes and break in surprising ways the rest
of the time. You can't ship them, you can't trust them, and when they
break at 3am Sunday you have no idea why.

So I built a real eval framework. On a real agent — a content-brief
generator that turns `(company, market)` into a complete SEO content
brief in ~10 minutes for ~$0.50.

**The four-layer eval system:**

1. **Deterministic.** Pure-function checks: did the model emit the
   required schema? Did the brief have ≥3 sections? Are the queries
   numbered 1..N? Sub-millisecond, $0, blocking on failure.

2. **LLM-as-judge.** 5 Haiku judges — buyer-realism, brief-specificity,
   brand-voice match, search-intent alignment, brief actionability. Each
   rubric lives as a Markdown file in `evals/rubrics/`. PR diffs read
   like English. The judges are advisory (logs only); deterministic
   checks are the blocking gate.

3. **Regression suite.** 30 cassette-replayed cases across 30 industries.
   Cassettes are keyed by `sha256(system_prompt + user_message + model)`,
   so any prompt edit forces a `RegressionStaleCassetteError` with a
   loud diff. Deterministic replay = $0 per CI run. Smoke tier (5 cases)
   runs on every pre-commit. Full tier (30 cases) runs on every PR via
   GitHub Actions.

4. **Production monitoring.** Streamlit dashboard reading the agent's
   SQLite write-log:
   - per-skill pass rate over time
   - cost p50/p95/max + histograms
   - 7-day rolling drift vs the prior 7-day baseline
   - 10% production sample → human review queue
   - judge-vs-human divergence (rubric recalibration signal)

**The proof:**

I deliberately broke `score_queries.composite = 5.0`. Watch:

- Local: `pytest -m regression_smoke` flips 3 of 5 cases red in 7
  seconds. The 3 cases with real-LLM cassettes catch it; the 2 with
  bootstrap cassettes don't react (a separate signal: real-LLM cassettes
  catch real regressions; fake cassettes only catch deterministic bugs).
- GitHub Actions: the regression workflow runs both tiers + posts a
  sticky PR comment naming the failed cases with truncated failure
  messages.
- Branch protection: with the gate in place, the PR cannot merge.

Revert the bug → green in another 7 seconds. GIF capture procedure
in `docs/regression_gate_demo.md`.

This is the loop the entire framework exists to drive: judges keep up
with human taste over time, instead of decaying silently after first
deployment.

**Stack:** Python 3.13, Anthropic SDK (Sonnet 4.6 + Haiku 4.5), Pydantic
v2 contracts, SQLite + sqlite-vec, fastembed (CPU ONNX), pytest, ruff,
Streamlit, GitHub Actions. ~160 tests, 30 regression cases, runs in
under 10 seconds.

→ github.com/lstrycharz/geoquery
→ Full eval framework writeup: `EVALS.md`
→ Regression gate demo: `docs/regression_gate_demo.md`
→ Architecture: `ARCHITECTURE.md`

The regression-gate experience alone — the discipline of converting
"that bug got past us" into "that bug now has a permanent test" —
separates this from 95% of agent code I see in the wild.
