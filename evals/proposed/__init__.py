"""evals/proposed/ — landing zone for meta-agent-authored evals (v3).

The meta-agent may add net-new evaluators here (it's on its edit-surface
allowlist). They are NOT auto-discovered or auto-run — a human wires an
approved one into the relevant skill's `make_evaluators()` on merge. Auto-
running a meta-agent-authored eval would itself be a reward-hacking surface.

`meta.meta_evals.trivial_eval_check` runs every file here against the
protected known_good / known_bad corpus before a proposal can merge.
"""
