# Self-Improvement (v3)

> **Status: in progress.** This document is seeded in v3 chunk 7 and completed
> in chunk 11. It will gain the full per-mechanism walkthroughs and the
> reward-hacking-defense section as those chunks land.

v1 demonstrated *decomposition*. v2 demonstrated *evaluation discipline*. v3
demonstrates *self-improvement* — the system uses its own eval history to make
future output better, and a meta-agent proposes its own changes.

## The four mechanisms

1. **Inner-loop revision** (`skills/base.py`) — consensus-gated judges: a lone
   judge failing stays advisory, a majority gates a revision. Retry-cap
   exhaustion writes a rich `escalations` row.
2. **Memory-driven improvement** (`memory/semantic.py`, `evals/winning_patterns.py`)
   — semantic memory tags briefs with eval scores; new runs retrieve the
   highest-scoring similar briefs as few-shot examples; `winning_patterns`
   distills structural lessons from the best briefs.
3. **Outcome-driven feedback** (`skills/predict_outcome.py`) — an Opus "30-day
   outcome judge" predicts whether a brief would have produced a top-10
   article. **See the honesty note below.**
4. **Meta-agent** (`meta/`) — a weekly cron reads the eval history, identifies
   one systematic pattern, proposes one constrained change, and opens a PR.
   The 6 meta-evals are the reward-hacking defense.

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
the outcome judge asks *would this actually work*. But a proxy that pretended
to be ground truth would be worse than no proxy. So it never pretends.

When (if) real ranking data is wired in later, it replaces the prediction —
the table and contract are shaped to make that a drop-in, not a rewrite.
