# Regression-gate demo — "AI doesn't have evals? It's a science project."

A 60-second walkthrough of the gate catching a real regression. Run it
locally with one terminal window — every step prints something concrete
the gate produces.

## Setup

You need the 3 live-recorded smoke cassettes (Notion, Stripe, Webflow)
plus the 2 still-bootstrap cassettes (Linear, Glossier). The bootstrap
cassettes won't react to the bug we're about to introduce — only the
live ones will. That asymmetry is the point: the gate catches regressions
that materialize in real-LLM behavior.

Make sure everything is green before starting:

```bash
pytest -m regression_smoke -q
# ..... 5 passed
```

## Step 1 — Introduce a deliberate bug

Open `skills/score_queries.py`. After the model returns the scored
queries, force every `composite` field to 5.0. This collapses
`select_priority_query`'s ranking signal — it picks the first query
by position instead of by composite score, which means the brief gets
written about a top-of-funnel novice query no matter how strategic the
ICP-segment actually wants something else.

Apply this patch (the only line that matters is the one in the middle):

```python
# in skills/score_queries.py, inside _coerce_output() right before the return:
for sq in parsed.scored:
    sq.composite = 5.0
```

## Step 2 — Watch the gate trip

```bash
pytest -m regression_smoke -q
```

The 3 live-cassette cases (Notion, Stripe, Webflow) flip
`BriefSpecificityJudge` from pass to fail because the brief now targets
the wrong query. The 2 bootstrap cases (Linear, Glossier) pass because
their fake LLM responses don't react to the input change — the cassette
serves the same content regardless of what the agent asked for.

Expected output:

```
FAILED tests/test_regression.py::test_regression_smoke[notion_b2b_saas]
FAILED tests/test_regression.py::test_regression_smoke[stripe_payments]
FAILED tests/test_regression.py::test_regression_smoke[webflow_nocode]
3 failed, 2 passed in ~7s
```

This is the gate doing its job. In GitHub Actions on a real PR, the
"regression / regression" check is now red, and the workflow's PR
comment names the three failed cases by slug plus the truncated
`BriefSpecificityJudge` failure message.

## Step 3 — Revert and re-verify

Roll back the patch (`git checkout skills/score_queries.py` if you
stashed or committed it locally; otherwise just delete the inserted
line).

```bash
pytest -m regression_smoke -q
# ..... 5 passed
```

## Step 4 — Optional: bigger demo with the full tier

`pytest -m regression_full -q` runs the 25 bootstrap-cassette cases.
The bug from Step 1 doesn't trip them — only the 3 live cases see real
behavior. That's the cost/coverage tradeoff: bootstrap-cassette cases
exercise the harness across 30 slugs, but they only flip on regressions
in deterministic code paths (contracts, parsing, orchestration). Real
prompt regressions need real-LLM cassettes.

To grow the gate's real-LLM coverage, see EVALS.md → "Adding a
regression case" → live-recording subset patterns.

## Step 5 — Capture the GIF

This document is the script. For the LinkedIn / portfolio asset:

1. Open a terminal at the project root.
2. Start `asciinema rec docs/regression_gate_demo.cast`.
3. Run Steps 1–3 inline.
4. Stop with Ctrl-D.
5. Convert to GIF with `agg docs/regression_gate_demo.cast docs/regression_gate_demo.gif`.

The whole demo takes 60–90 seconds end-to-end.
