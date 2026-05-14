# Meta-agent PR — reviewer guide

A `meta-agent/*` PR is opened by `python -m meta.run` (weekly cron, v3 chunk 9).
It carries **one** bounded change proposed against **one** detected pattern.
The 6 meta-evals (`.github/workflows/meta-agent-gate.yml`) have already run —
but a green gate is the floor, not the ceiling. **You** are the merge gate.

## What the gate already checked

| Check | Guarantees |
|---|---|
| `protected_path` | Only `skills/prompts/`, `evals/rubrics/`, `evals/proposed/` touched; no rubric loosened. |
| `trivial_eval` | Any new eval passes the whole `known_good` corpus and fails the whole `known_bad` corpus. |
| `cassette_integrity` | `regression_dataset/` untouched. |
| `single_change` | One file. |

## What only a human can check — read the actual diff

- [ ] **Root cause, not symptom.** The hypothesis explains *why* the pattern
      happened, and the diff addresses that — not just the surface metric.
- [ ] **No Goodharting.** The change improves the *work*, not the *grader*.
      A change that makes briefs the judges like but a writer wouldn't act on
      is a failure even with a green gate.
- [ ] **Tightening, not loosening.** If a rubric changed, it raised a bar.
- [ ] **Wiring instructions present.** If a new eval was added under
      `evals/proposed/`, the description says exactly which skill's
      `make_evaluators()` to wire it into. Do that wiring deliberately on
      merge — there is no auto-discovery, and that's on purpose.
- [ ] **Measurable.** The predicted effect is something `meta/measure.py` can
      check after merge (chunk 9). Vague predictions can't close the loop.
- [ ] **You read the diff.** Not just this description. The description is the
      meta-agent's claim about its change; the diff is the change.

## After merge

`meta/measure.py` snapshots the baseline and, after N post-merge runs in the
named segment, reports effect size + before/after means + n. A clearly
negative measurement triggers an automatic revert PR — the loop closes both
directions, so a merge is reversible if the prediction doesn't hold.
