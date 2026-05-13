# Regression-gate demo — "AI doesn't have evals? It's a science project."

A 60-second walkthrough of the gate catching a real regression. Single
terminal window, ~7 seconds of pytest per direction, every step prints
something concrete that the gate produces.

The demo's key insight: because cassettes are keyed by
`sha256(system_prompt + user_message + model)`, **changing an upstream
skill's output changes downstream prompts → cassette miss → loud
failure with a re-record instruction.** No judge needs to disagree;
the prompt-hash mechanism is the gate itself.

## Setup

Verify everything is green before starting:

```bash
pytest -m regression_smoke -q
# .....   5 passed in ~7s
```

## Step 1 — Introduce a deliberate bug

Open `skills/score_queries.py`. After the existing `make_evaluators`
method, add a `run` override that collapses every `composite` to 5.0.
This destroys the score signal that `select_priority_query` reads.

Patch:

```python
    def run(self, inputs):
        result = super().run(inputs)
        for sq in result.output.scored:
            sq.composite = 5.0
        return result
```

## Step 2 — Watch the gate trip

```bash
pytest -m regression_smoke -q
```

Expected: **all 5 cases fail** with the same root cause —
`RegressionStaleCassetteError` on the `select_priority_query` skill.
The error message names the exact 16-char cassette-key prefix that
missed and includes the model + first 80 chars of the system prompt
and user message, so you can see at a glance what changed.

```
FAILED tests/test_regression.py::test_regression_smoke[notion_b2b_saas]
FAILED tests/test_regression.py::test_regression_smoke[stripe_payments]
FAILED tests/test_regression.py::test_regression_smoke[webflow_nocode]
FAILED tests/test_regression.py::test_regression_smoke[linear_b2b_saas]
FAILED tests/test_regression.py::test_regression_smoke[glossier_dtc_beauty]

  AssertionError: [notion_b2b_saas] run status drifted: got 'failed', expected 'completed';
  error="no cassette entry for key 4cadc74d0e6fbcd0…:
  model='claude-sonnet-4-6',
  sys[:80]='# Select Priority Query — Strategic Choice, Not Pure Argmax\n\nYou are a senior co',
  usr[:80]='ICP segment: Distributed Engineering Lead at 200-500 dev shop\nBuyer role: Direct'.
  If the prompt change was intentional, re-record this cassette."

5 failed, 240 deselected in ~7s
```

This is the gate doing its job. In GitHub Actions on a real PR, the
`regression` check is now red, the workflow's sticky PR comment names
the 5 failed cases, and the ruleset blocks merge.

## Step 3 — Revert and re-verify

Delete the `run` method from `skills/score_queries.py` (or
`git checkout skills/score_queries.py` if you didn't commit it).

```bash
pytest -m regression_smoke -q
# .....   5 passed in ~7s
```

Green in 7 seconds. The whole detect-and-recover loop takes under 60s
total.

## Notes

**Why all 5 cases fail, not just the live ones:**

You might expect the 3 live-recorded cassettes (Notion, Stripe, Webflow)
to fail but the 2 bootstrap cassettes (Linear, Glossier) to pass through
unchanged — fake-client cassettes serve canned responses regardless of
input, right?

That's true *within a skill call*. But the inputs to *downstream* skills
depend on *upstream* outputs. When `score_queries` outputs 5.0
composites, the user message that gets built for `select_priority_query`
changes — different scored-query JSON in, different prompt, different
sha256 hash, cassette miss. This is true for both live and bootstrap
cassettes equally.

The asymmetry between live and bootstrap matters for bugs that *only*
affect a single skill's eval verdict — e.g. weakening a rubric. There,
live cassettes catch the regression (real Sonnet output trips the new
weaker rubric differently) while bootstrap cassettes don't react. But
for any bug that changes an upstream skill's output, **the hash chain
catches everything.**

## Step 4 — Capture the GIF

This document is the script. For the LinkedIn / portfolio asset:

```bash
asciinema rec docs/regression_gate_demo.cast
# Run Steps 1-3 inline, then Ctrl-D to stop.
agg docs/regression_gate_demo.cast docs/regression_gate_demo.gif
```

Recording tips:

- Resize your terminal to about 100 cols × 30 rows before starting
  (`agg` defaults look best at that aspect ratio).
- Pre-arrange your editor next to the terminal so the patch in Step 1
  takes one paste, not 30s of typing.
- Don't speak while recording; we'll add a caption track afterward (or
  ship it silent).

The whole demo runs in 60-90 seconds end-to-end.
