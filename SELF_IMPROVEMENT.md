# Self-Improvement (v3)

v1 demonstrated *decomposition* — one job split cleanly across seven skills and
six layers. v2 demonstrated *evaluation discipline* — a four-layer eval system
and a regression gate that has caught a bad change on camera. **v3 demonstrates
*self-improvement*** — the system uses its own eval history to make future
output better, and a meta-agent proposes its own changes.

The hard part of self-improvement isn't the loop. It's stopping the loop from
*cheating*. An agent told to "improve the eval scores" will, given the chance,
weaken a rubric, edit a regression baseline, add a trivially-passing eval, or
push briefs toward verbose patterns the judges like and humans don't. That
failure mode — **reward hacking** — is the thing v3 is actually about. The four
mechanisms below are the easy part; the [reward-hacking defense](#the-reward-hacking-defense)
is the point.

The guiding principle is the [`autoresearch`](https://github.com/karpathy/autoresearch)
lesson: **lock down the eval metric, the data, and the scope — let only the
agent's reasoning vary.**

---

## The four mechanisms

### Mechanism 1 — Inner-loop revision (`skills/base.py`)

When a skill's output fails its evaluators, the skill re-runs with a revision
header prepended — bounded at 3 attempts. v3 made the trigger smarter:

- **Consensus gating.** A deterministic eval failing always gates a revision.
  Judges (the LLM-as-judge evaluators) are now *consensus-gated*: a single
  judge failing stays advisory, but when a **majority** of a skill's judges
  fail, a revision fires. This is the robust middle — pure-advisory under-reacts
  (it ships briefs multiple judges flagged), full re-gate thrashes on one noisy
  judge call.
- **Full-critique revision header.** When a revision fires, *every* failing
  critique goes into the header — deterministic and judge alike, even the
  non-gating ones — so the model sees the whole picture, not just the gate.
- **Escalation signal.** On retry-cap exhaustion the skill raises
  `SkillEscalation`, carrying every attempt's failures plus the final rejected
  output. `agent.py` writes that into the `escalations` table. A clustered
  escalation (one skill exhausting its retries repeatedly) is the meta-agent's
  richest input — it means the skill couldn't produce passing output *at all*.

### Mechanism 2 — Memory-driven improvement (`memory/`, `evals/winning_patterns.py`)

The agent's semantic memory of past briefs becomes *score-aware*:

- Every indexed brief is tagged with `eval_score` (a 0-1 composite) and a
  `section_skeleton` (its headings, joined).
- `find_similar(rank_by_eval_score=True)` pulls a wide distance-candidate set,
  re-ranks it by `eval_score`, and returns the **top-5 highest-scoring** similar
  briefs — so the drafter's few-shot examples are *high-performing* briefs, not
  merely *nearby* ones. They're injected slim (angle + section skeleton, ~200
  tokens each), not as full bodies.
- `geoquery extract-patterns` runs an LLM call over the top-N highest-scoring
  briefs and distills the **structural patterns** they share ("high-scorers
  name a specific persona pain in the angle; 5-6 sections; …") into the
  `winning_patterns` table. The drafter injects the latest row as guidance.
  This is periodic, not per-run — the few-shot examples carry *shape*, the
  winning patterns carry the *deep lessons*.

### Mechanism 3 — Outcome-driven feedback (`skills/predict_outcome.py`)

A stronger model (Opus) plays "30-day outcome judge": given a finished brief,
it predicts whether an article written to it would have reached the top 10.

- `geoquery predict-outcomes` runs this as a batch command over a **sampled
  subset** — the same 10% the human-review sampler picks, plus any already-
  high-scoring run worth a second opinion. Opus is ~5× Sonnet; full coverage
  isn't worth it, and the per-run hot path stays Opus-free.
- The prediction blends back into `eval_score`: `blend_eval_score` mixes the
  judge pass rate with the predicted-outcome signal at a 0.6 / 0.4 weight, so
  the simulated signal informs the score without dominating the real one.
  Briefs with high predicted outcomes float to the top of Mechanism 2's
  retrieval and the winning-patterns extraction.
- **This is a *simulated* signal.** See [the honesty note](#honesty-note--the-outcome-signal-is-simulated).

### Mechanism 4 — The meta-agent (`meta/`)

A weekly GitHub Actions cron reads the week's eval traces, identifies one
systematic pattern, proposes one specific change, and opens a PR. A human
reviews and merges. The PR's effect is measured after merge.

```
analyze ──▶ propose ──▶ open PR ──▶ [6 meta-evals gate] ──▶ human review ──▶ merge
   │           │                                                              │
rule-based   single LLM call                                          measure.py
no LLM       blind to rubric prose                              (effect size, n,
                                                                 auto-revert on
                                                                 clear regression)
```

- **`analyze.py`** — rule-based, **no LLM**. It reads the episodic DB read-only
  and returns a deterministic, severity-ranked list of patterns from five
  signals: drift windows, judge-human divergence, escalation clusters, a low
  predicted-outcome rate, and stale winning-patterns. Rule-based *on purpose* —
  if an LLM picked which pattern to "discover", the meta-agent could cherry-pick
  the one easiest to game. It also skips any pattern a rejected/inconclusive
  proposal already targeted in the last 30 days — no re-proposing the same
  thing every week.
- **`propose.py`** — the *single* LLM call. It takes the top-ranked pattern and
  the affected skill's **actual outputs**, and emits one diff + one hypothesis
  + one predicted effect. **It is never shown the rubric prose of the judges it
  is optimizing against** — see the defense section.
- **`run.py`** — the public entry point. `python -m meta.run --dry-run` prints
  the proposal; without `--dry-run` it opens a real PR on a `meta-agent/*`
  branch and records a `meta_proposals` row.
- **`measure.py`** — post-merge attribution. When a `meta-agent/*` PR merges,
  `meta-agent-measure.yml` snapshots the pre-merge eval-score window. Later,
  once 20 post-merge runs exist, `measure.py` compares the windows and reports
  the effect — and **a clearly-negative measurement opens an automatic revert
  PR**. The loop closes both directions; the meta-agent can't ratchet only
  upward.

---

## The reward-hacking defense

Every defense below exists to answer one question: *what stops the meta-agent
from gaming its own eval?* They are **core, not polish**.

### 1. A constrained edit surface (`meta/edit_surface.py`)

Deny-by-default. The meta-agent may only touch `skills/prompts/*.md`,
`evals/rubrics/*.md`, and net-new files under `evals/proposed/*.py`. Everything
else — the regression dataset, the golden set, `evals/regression.py`,
`evals/production.py`, `memory/`, `.github/`, `meta/` itself, `agent.py`,
`contracts.py`, `config.py`, `pyproject.toml` — is hard-denied. It can't edit
the graders, the baselines, the orchestrator, or its own allowlist.

### 2. `propose.py` is blind to the rubric prose (anti-Goodhart)

The single LLM call sees the *pattern* (what regressed) and the *actual skill
outputs* (the work) — **never the grader's text**. If it could read the rubric,
it would optimize against the rubric. Seeing only the outputs forces it to
improve the actual work. `test_meta_propose.py` asserts this property directly:
no rubric file's content appears in the prompt context.

### 3. The 6 meta-evals (`meta/meta_evals.py`)

Run by `.github/workflows/meta-agent-gate.yml` on every `meta-agent/*` PR:

1. **Protected-path check** — fails if the diff touches a denied path, or if a
   rubric edit *loosens* a bar (a lowered numeric threshold, or a softened
   directive: `MUST` → `SHOULD`). Tightening is allowed; loosening is not.
2. **Trivial-eval check** — every new `evals/proposed/*.py` is run against a
   protected corpus: it must FAIL all `known_bad` fixtures and PASS all
   `known_good` ones. Rejects always-pass evals (no signal) *and* always-fail
   evals (block healthy work).
3. **Divergence-regression check** — judge-vs-human divergence must not rise
   under the proposed config.
4. **Cassette-integrity check** — `regression_dataset/` is untouched.
5. **Verbosity guard** — median brief length can't grow >15% without a matching
   human-rating gain. Judges like longer briefs; humans often don't.
6. **Single-change check** — one logical change per proposal: one prompt edit
   OR one new example OR one new eval.

### 4. The CI gate runs trusted code

`meta-agent-gate.yml` checks out `meta/` from the **base branch** before
running the meta-evals — never the PR head. A meta-agent that edits its own
`edit_surface.py` to widen its allowlist is caught by the trusted copy.

### 5. An immutable baseline (`meta/baseline.py` + `baseline.json`)

`baseline.json` holds sha256 hashes of every rubric and every denylisted eval
module. `verify_baseline` detects tampering with the grading logic. A committed
test asserts the snapshot stays in sync with the repo.

### 6. A read-only DB handle

`analyze.py` opens the episodic DB with `mode=ro` — the meta-agent cannot
delete a drift row to manufacture (or erase) a pattern.

### 7. Net-new evals are human-wired, not auto-discovered

An approved `evals/proposed/*.py` does not run automatically. A human wires it
into a skill's `make_evaluators()` deliberately on merge. Auto-running a
meta-agent-authored eval would itself be a reward-hacking surface.

### 8. A PR-write-only token

The meta-agent's GitHub token is a fine-grained PAT scoped to **open PRs only**
— no merge, no branch-protection edit, no push to a protected branch. A leaked
token can't bypass the gate.

### 9. No statistical theater

`meta/stats.py` reports honest primitives — before/after means, delta, effect
size, and an `underpowered` flag — and **no significance test**. 20 runs/week
can't support a t-test, and faking one would be the statistical version of the
exact reward hacking this layer guards against. Most proposals will read
"inconclusive". That's correct, not a bug.

---

## Honesty note — the outcome signal is *simulated*

Mechanism 3 does **not** use real search-ranking data. There is no Search
Console integration, no backlink data, no 30-day wait-and-measure. The
`predict_outcome` skill is an LLM (Opus) reasoning *from the brief alone* about
whether an article written to it *would likely* rank — it is a **prediction, a
proxy, a simulation**. It is labelled that way everywhere it appears:

- the `outcome_predictions` table comment,
- the `OutcomePrediction` contract docstring,
- the `predict_outcome` prompt itself ("you have no ranking data"),
- the `geoquery predict-outcomes` command help text.

Why include a simulated signal at all? Because a calibrated proxy still adds
information the judges don't have — the judges grade *conformance to a rubric*;
the outcome judge asks *would this actually work*. But a proxy that pretended to
be ground truth would be worse than no proxy. So it never pretends — and it's
mixed into `eval_score` at only 0.4 weight, behind the real judge signal.

When (if) real ranking data is wired in later, it replaces the prediction — the
table and contract are shaped to make that a drop-in, not a rewrite.

---

## Running the meta-agent

```bash
# Dry run — print the proposal the meta-agent would open, no PR, no spend
# beyond one LLM call. Reads the committed demo DB by default.
python -m meta.run --dry-run

# Extract winning patterns from the highest-scoring briefs (Mechanism 2)
geoquery extract-patterns --top-n 10

# Predict outcomes for the sampled subset (Mechanism 3) — uses Opus
geoquery predict-outcomes --limit 10

# The CI gate, run locally against a meta-agent/* branch's diff
python -m meta.gate

# Post-merge measurement pass (normally the weekly cron runs this)
python -m meta.measure --measure-all
```

The weekly cron (`.github/workflows/meta-agent-cron.yml`) runs `meta.run` +
`meta.measure --measure-all`. The merge hook (`meta-agent-measure.yml`)
snapshots the baseline. Both need `META_AGENT_PAT` (a PR-write-only fine-grained
token) and `ANTHROPIC_API_KEY` in the repo's Actions secrets.

---

## Deferred manual step — the 3 real merged PRs

v3 ships the **full meta-agent mechanism** — analyze, propose, the 6-eval gate,
the cron, post-merge measurement, auto-revert — verified end to end with
`--dry-run` against the demo DB and ~290 tests.

What it does **not** ship is three *real, merged* meta-agent PRs with measured
effects. That needs real trace history — enough actual runs that `analyze.py`
surfaces a genuine pattern worth acting on. It is a documented one-time step the
maintainer runs once that history exists:

1. Accumulate real run history (`geoquery brief …` over time, or a backfill).
2. Let the weekly cron fire — or run `python -m meta.run` manually — to open a
   real `meta-agent/*` PR.
3. Review it against `docs/meta_agent_pr_template.md`, merge if sound.
4. `meta-agent-measure.yml` snapshots the baseline; after 20 post-merge runs,
   the cron's measurement pass reports the effect.
5. Repeat until 3 PRs have been merged and measured. The Learning Curve page's
   annotations then become real instead of demo-seeded.

This is the same pattern as v2's deferred live-cassette recording: the
*mechanism* is built and tested now; the step that needs accumulated real-world
data is documented for when that data exists.
