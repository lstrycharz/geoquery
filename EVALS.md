# EVALS — Trust Layer for the GEO Query Agent

> v1 demonstrated *decomposition*: 7 skills, 6 layers. v2 demonstrates *evaluation discipline*: a four-layer eval system, a regression gate, a production sample stream, a Streamlit dashboard. This doc is the reader's entry point to all of it.

## The four layers

| Layer | What it does | Where it lives | When it runs |
|---|---|---|---|
| **1. Deterministic** | Schema validity, word counts, required sections, position monotonicity. Sub-millisecond, $0, blocking by default. | `evals/deterministic.py` | After every skill, before the next one starts |
| **2. LLM-as-judge** | Brand voice, search intent alignment, query realism, brief specificity, brief actionability. Haiku-graded, advisory (logs only, doesn't gate). | `evals/model_graded.py` + rubrics in `evals/rubrics/*.md` | After every skill; surfaces in episodic log + dashboard |
| **3. Regression suite** | 30+ cassette-replayed cases. Asserts the *evaluation profile* matches a recorded baseline. Deterministic, $0 per run. | `regression_dataset/<slug>/` + `tests/test_regression.py` | Pre-commit (smoke, 5 cases), PR CI (full, 30+ cases), weekly cron (live, 5 cases) |
| **4. Production monitoring** | Daily eval scores, 7-day drift, cost histograms, tool failure rates, human-review queue. | `dashboard/` (Streamlit) + `evals/production.py` | Continuous; reads `data/episodic.db` |

## Rubric catalog

Every LLM-judge prompt lives as a Markdown file under `evals/rubrics/`. PR diffs read like English; the judge prompts are first-class reviewable artifacts.

| Rubric | Judges | Asserts |
|---|---|---|
| `buyer_realism.md` | Query list from `generate_geo_query_list` | ≥70% of queries read like real buyer phrasing (not SEO-professional) |
| `brief_specificity.md` | `ContentBrief` from `draft_content_brief` | Angle is specific + differentiated, not generic listicle-fodder |
| `brand_voice_match.md` | `ContentBrief` × `CompanyDossier` | Brief's prose register matches the company's brand voice |
| `search_intent_alignment.md` | `ContentBrief` × `Priority` (query + framing) | Brief actually serves the priority query's intent (topical + framing), not an adjacent topic |
| `brief_actionability.md` | `ContentBrief` (sections + key_points) | ≥80% of key_points are concrete directives, not category placeholders a writer would have to invent from |

## Adding a new judge

1. Write the rubric in `evals/rubrics/<judge_name>.md`. Use `{placeholders}` if you need substitution; escape literal braces as `{{` / `}}`.
2. Add a judge class in `evals/model_graded.py`. Mirror an existing one — dataclass with `client`, `budget`, `name`, `blocking=False`, `rubric=<judge_name>`. Implement `evaluate(output) -> EvalResult`.
3. Attach it from the relevant skill's `make_evaluators(inputs) -> list[Evaluator]`. The skill loop calls `ev.evaluate(skill_output)` — pass any extra context (e.g. an upstream dossier) by baking it into the judge's dataclass at construction time, like `BrandVoiceMatchJudge` does.
4. Add cassette + unit tests under `tests/test_evals_judge_<name>.py`.
5. Document the rubric in this file's catalog.

## Adding a regression case

Each case is a directory under `regression_dataset/<slug>/` with three files:

```
regression_dataset/notion_b2b_saas/
├── input.json       # {company, market, sitemap_url?}
├── cassette.json    # sha256(sys_prompt + user_msg + model) → recorded response
└── expected.json    # {eval_profile: {skill_name: pass_bool}, status, notes}
```

To add a new case:

1. Append `(slug, company, market)` to `_SMOKE_CASES` in `tests/test_regression_record.py`.
2. Run `pytest -m regression_record` — this writes the three files for your new slug into `regression_dataset/<slug>/`.
3. Open `expected.json` and sanity-check the recorded `eval_profile` is what you actually want as the baseline. The replay test asserts no skill flips from this baseline.
4. Run `pytest -m regression_smoke` to confirm the new case replays cleanly.
5. Commit all three files.

The smoke tier today ships with cassettes recorded against the existing `FakeAnthropicClient` fixtures (cheap + deterministic; same fake response per skill regardless of input). To upgrade any subset of cases to **real-LLM** cassettes:

```bash
# Re-record the 5 smoke cases (~$2.50):
pytest -m regression_record_live -k 'notion or linear or glossier or stripe or webflow'

# Re-record the entire 30-case dataset (~$15):
pytest -m regression_record_live

# Re-record one specific slug:
pytest -m regression_record_live -k notion_b2b_saas
```

Requirements: a real `ANTHROPIC_API_KEY` in `.env`. The test is skipped automatically if the key is the test stub. Each case costs ≈$0.50 (one full agent run: 7 skill calls + 6 judge calls on Sonnet/Haiku). The per-case budget cap is set to $1.50 in the `live_settings` fixture; edit if you need headroom.

After live recording, `expected.json` is stamped `source: "live-anthropic"` so the dataset's mix of bootstrap-vs-live cases is auditable in PR diffs.

## Re-recording a regression cassette after an intentional prompt change

When you intentionally change a system prompt or an upstream contract, the cassette hashes shift. Replay raises `RegressionStaleCassetteError` with the model + truncated prompt previews so you can identify which call regressed.

If the change was intentional:

```bash
pytest -m regression_record   # refreshes regression_dataset/*/cassette.json + expected.json
pytest -m regression_smoke    # verifies replay still passes
git add regression_dataset/
git commit -m "regression: re-record after <prompt-change-description>"
```

Reviewers see two diffs in the PR: the prompt-change diff (semantic) and the cassette/expected diff (mechanical). Reviewing the second one tells you what actually changed in the model's behavior, not just the prompt text.

## Reading the dashboard

```bash
pip install -e ".[dashboard]"
streamlit run dashboard/app.py
```

Five pages, all read-only over `data/episodic.db` (or the committed `data/episodic.demo.db` if no real DB exists yet):

| Page | What it shows | Built from |
|---|---|---|
| **Landing (Runs)** | Recent runs table + global drift banner if any skill is regressing | `dashboard/data.py::recent_runs` + `evals/production.py::compute_drift_windows` |
| **Evals** | Per-skill pass-rate line chart over time + totals table | `pass_rate_per_skill_per_day` |
| **Costs** | p50 / p95 / max metric cards, histogram, cost-over-time trend, top-10 most expensive runs | `cost_per_run` |
| **Tools** | Per-skill failure-rate bar chart (`eval_passed = 0` OR `IS NULL`) | `skill_failure_rate` |
| **Drift** | 7-day rolling pass-rate vs prior 7-day; per-skill window table + sorted-delta bar chart; judge-vs-human divergence panel | `compute_drift_windows` + `compute_judge_human_divergence` |
| **Review Queue** | Pending sampled runs; one-at-a-time form (overall + 3 per-dim sliders + notes) writes back to `human_reviews` | `pending_reviews` + `judge_outcomes_for_run` |

The dashboard never writes to the DB except through `dashboard/pages/5_Review_Queue.py`'s parameterized review-submit step. All SQL lives in `dashboard/data.py` (deep module, unit-tested) — pages are thin presentation.

## Production sample stream + judge recalibration loop

`agent.run_brief` rolls a `random()` die on every completed run; with probability `SAMPLE_RATE` (default 10%) it inserts a `human_reviews` row marked pending. The dashboard's Review Queue page surfaces those pending rows.

The reviewer submits a 1-5 overall rating plus three per-dimension ratings (brand voice, search-intent fit, actionability). `evals/production.py::compute_judge_human_divergence` then compares the judges' run-time consensus (all `eval_passed = 1`?) against the human's verdict (rating ≥ 3 = pass) for every reviewed sample in the last 7 days.

When divergence > 5%, the Drift page lights up a warning. The recalibration step is manual: open the offending judge's rubric in `evals/rubrics/*.md`, look at the reviewer notes from the divergent cases, tighten the rubric, and re-record affected smoke cassettes (`pytest -m regression_record_live -k <slug>`). PR reviewers see the rubric diff next to the cassette diff and can verify the change behaves as intended.

This is the loop the entire framework exists to drive: judges keep up with human taste over time, instead of decaying silently after first deployment.

## Drift detection

`evals/production.py::compute_drift_windows` runs a single grouped CTE over `skill_invocations` and returns one `DriftWindow` per skill: current 7-day pass rate, prior 7-day pass rate, delta. `drift_detected` fires when:

- `delta ≤ -10%` (configurable; default in `DEFAULT_DRIFT_THRESHOLD`), AND
- both windows have `≥ 5` invocations (small-N noise guard).

The dashboard landing page renders a banner when any skill is drifting. The Drift page renders the full table + a sorted-delta bar chart so it's obvious which skill regressed.

Optional Slack alerting: `post_drift_alert_to_slack(windows, webhook_url=...)` posts a per-skill summary message via a webhook. No-op when the URL is empty. Wire it into a scheduled cron (the workflow at `.github/workflows/regression.yml` is a natural host — it already has `pytest -m regression_full` data available; just add a post-step that runs `python -c "from evals.production import ..."`).

## Cassette format invariants

Two non-obvious rules the cassette dump must preserve:

- **Outer mapping sorted by hash key** — diff-friendly. Re-recording produces stable file order regardless of call sequence during recording.
- **Inner `tool_use.input` dict insertion order PRESERVED** — Pydantic's `model_dump_json` follows declaration order for top-level fields, but for `dict[str, X]` fields (e.g. `CompanyDossier.swot`) it preserves the insertion order of the input dict. Sorting inner-dict keys would silently make replay diverge from record. See `evals/regression.py::dump_cassette` for the (terse) implementation.

## The pedagogical regression-gate demo

A 60-second demonstration that the gate catches real regressions: force `score_queries.composite = 5.0` → `select_priority_query` collapses to first-by-position → the brief targets the wrong query → `BriefSpecificityJudge` flips pass→fail on the 3 live cassettes (Notion, Stripe, Webflow) → CI gate trips with a PR comment → revert → green.

Step-by-step procedure with the exact patches and expected output lives in [`docs/regression_gate_demo.md`](docs/regression_gate_demo.md). Use it as the asciinema script.

Note the interesting asymmetry: the 2 bootstrap-cassette cases (Linear, Glossier) pass through unchanged because their fake LLM responses don't react to the bug. That's the live-vs-bootstrap coverage gap the live-recording work was meant to expose. The fix is to upgrade more cassettes to real-LLM (`pytest -m regression_record_live -k <slug>`, ~$0.50/case).
