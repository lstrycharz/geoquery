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

*(Chunks 2+ add `search_intent_alignment.md` and `brief_actionability.md`.)*

## Adding a new judge

1. Write the rubric in `evals/rubrics/<judge_name>.md`. Use `{placeholders}` if you need substitution; escape literal braces as `{{` / `}}`.
2. Add a judge class in `evals/model_graded.py`. Mirror an existing one — dataclass with `client`, `budget`, `name`, `blocking=False`, `rubric=<judge_name>`. Implement `evaluate(output) -> EvalResult`.
3. Attach it from the relevant skill's `make_evaluators(inputs) -> list[Evaluator]`. The skill loop calls `ev.evaluate(skill_output)` — pass any extra context (e.g. an upstream dossier) by baking it into the judge's dataclass at construction time, like `BrandVoiceMatchJudge` does.
4. Add cassette + unit tests under `tests/test_evals_judge_<name>.py`.
5. Document the rubric in this file's catalog.

## Adding a regression case

*(Populated in Chunk 3.)*

## Reading the dashboard

*(Populated in Chunk 6.)*

## Re-recording a regression cassette after an intentional prompt change

*(Populated in Chunk 3.)*

## The pedagogical regression-gate demo

*(Populated in Chunk 8: force all `score_queries.composite` to 5.0; watch `BriefSpecificityJudge` flip pass→fail on three cases; revert; watch green.)*
