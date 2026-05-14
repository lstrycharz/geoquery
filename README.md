# GEO Query → Content Brief Agent

**You type two things in. Ten minutes later you get a complete article plan out.**

```
$ geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

Out comes a finished brief that a writer can use to draft the article: who it's for, the specific angle to take, what sections to write, what to cover in each one, what sources to cite, how long it should be, and which pages on your own site to link to.

It costs about **30 to 60 cents** per brief and takes **5 to 10 minutes**. There are [eight real examples](./briefs/) in the repo across very different industries — knowledge software, payments, beauty, outdoor apparel, and more — that show what you actually get.

You can also see the agent's live performance dashboard at **[geoquery.streamlit.app](https://geoquery.streamlit.app)** — pass rates, costs, and quality trends over time.

---

## What it actually does

You give it:
- A **company name** (e.g. "Notion", "Glossier", "Patagonia")
- A **market or topic** (e.g. "B2B SaaS knowledge management", "DTC outdoor apparel")

It then does, in order, the work a senior content strategist would do:

1. **Researches the company** — what they sell, who their competitors are, where they're strong and weak.
2. **Figures out who the audience is** — 2 to 4 different types of buyers, including the exact phrases those buyers actually use.
3. **Lists 25 things those buyers would search for** — from broad questions ("what is a wiki") to specific ones ("notion vs confluence for engineering").
4. **Scores those 25 searches** — how much traffic, how hard to rank, how valuable to the business. (Uses real Google data if you give it a [DataForSEO](https://dataforseo.com/) account; otherwise estimates.)
5. **Picks the single best one to write about** — not just the highest-scoring one, but the one with the most strategic value.
6. **Looks at what's already on Google for that search** — reads the top 3 results to figure out what everyone is already saying.
7. **Writes the brief** — focused on a specific angle that doesn't repeat what's already out there.

Then it hands you a markdown file. You give it to a writer. They write the article.

---

## Why this exists (and why it might matter to you)

Most "AI agents" in the wild today are one giant prompt that hopes the AI does the right thing. They work sometimes and break in surprising ways the rest of the time, and there's no way to inspect what went wrong.

This one is built like a **small assembly line**. Each station does exactly one job — research the company, define the audience, brainstorm searches, score them, pick the best, study the competition, write the brief. Each station has its own instructions, its own quality checks, and can be improved without breaking the others.

That's the interesting bit. The brief is a useful byproduct of demonstrating that you can build agents this way — transparently, testably, and a piece at a time.

And on top of the assembly line, there's a whole **trust layer** — inspectors, a test box, an automatic doorman, a sampling room, and a dashboard — that makes the system catch its own regressions before they reach a real run. ([See "How we know it actually works"](#how-we-know-it-actually-works) below.)

**If you're trying to learn how to build agents that aren't black boxes,** the repo is meant to be read. The code is small (a few hundred lines per layer), every architectural choice is named, and [`ARCHITECTURE.md`](./ARCHITECTURE.md) explains *why* each one was made. [`EVALS.md`](./EVALS.md) covers the trust layer in detail.

---

## See it in action

Eight example briefs, real outputs from running the agent against real companies (no fake data; ~$3.85 of API spend produced these):

| Brief | Industry | The angle the agent picked |
|---|---|---|
| [Notion](./briefs/example_notion_b2b_saas_knowledge_mgmt.md) | B2B knowledge software | Single source of truth for product + engineering docs |
| [Linear](./briefs/example_linear_b2b_saas_project_mgmt.md) | Engineering project management | Linear vs Jira for a 20-person engineering team |
| [Glossier](./briefs/example_glossier_dtc_beauty.md) | DTC beauty | Good ingredients under $30 — skincare for minimalists |
| [Stripe](./briefs/example_stripe_payments_fintech.md) | Payments | The billing-reconciliation nightmare with Stripe |
| [Webflow](./briefs/example_webflow_nocode_design.md) | No-code design | Figma-to-live animation in a no-code builder |
| [HubSpot](./briefs/example_hubspot_smb_crm.md) | Small-business CRM | CRM with built-in email workflows (no Zapier) |
| [Vercel](./briefs/example_vercel_frontend_cloud.md) | Frontend cloud hosting | Alternatives to Vercel with predictable billing |
| [Patagonia](./briefs/example_patagonia_dtc_outdoor.md) | Outdoor apparel | Brands with lifetime repair programs |

Each brief is about 100 lines of markdown — open one and you can see what the agent actually produces.

---

## How we know it actually works

Most AI tools you can install today are like a bakery with no health inspector. They produce bread, sometimes good, sometimes terrible, and you only find out by eating it.

This one has five things that turn "hope it's OK" into "we'd notice immediately if it wasn't":

### 1. Quality inspectors at every station

**Five inspectors** look at each finished brief for specific things — does it sound like the brand actually talks? does it answer the right question? are the bullet points concrete or vague? They log everything they find so we can review later. (They give advice; they don't block briefs. Their notes show up in the dashboard so we can spot patterns.)

The inspectors' instructions are written in plain English in [`evals/rubrics/`](./evals/rubrics/) — anyone can read them, anyone can change them, every change shows up clearly in a code review.

### 2. A 30-piece test box

Thirty known-good products sit in a sealed box. Any change to the factory — tweak a worker's instructions, swap a recipe — has to run those 30 products through. If even one comes out different from what's in the box, the change is rejected.

The box is in [`regression_dataset/`](./regression_dataset/) and the comparison runs in 30 seconds.

### 3. An automatic doorman

A robot guard runs every time someone tries to update the factory ([on every pull request](https://github.com/lstrycharz/geoquery/actions/workflows/regression.yml)). He runs the 30-piece test box. Nothing gets in without his sign-off — GitHub's branch protection physically blocks the merge button until he approves.

We deliberately broke a worker on camera to see if he caught it. He did, in **14 seconds**, then opened back up when we fixed it. The procedure is in [`docs/regression_gate_demo.md`](./docs/regression_gate_demo.md) — run it yourself in a minute.

### 4. A sampling room

**1 in every 10 finished products** is pulled aside for a human to look at. The human rates it 1-to-5 and writes notes. The dashboard then compares what the inspectors said to what the human said.

If the inspectors keep saying "ship it" but humans keep saying "this is bad," we know the inspectors need retraining. The dashboard flags any inspector who disagrees with humans too often.

### 5. A live dashboard

A web page at **[geoquery.streamlit.app](https://geoquery.streamlit.app)** that shows everything happening on the factory floor: how many briefs the factory made, what each one cost, which inspectors flagged what, whether quality is slipping vs. last week, and the queue of briefs waiting for human review.

---

## It gets better on its own

The factory doesn't just run — it studies its own track record and improves.

**It learns from its best work.** Every finished brief is filed with a quality score. When the factory starts a new brief, it pulls up its *highest-scoring* past briefs on similar topics — not just similar ones — as worked examples. A weekly pass also distils what the best briefs have in common ("they name a specific reader's pain in the angle; they have 5-6 sections") and feeds that back in as a checklist.

**It predicts whether the work would actually land.** A second, stronger reviewer looks at a sample of briefs and predicts whether an article written to each one would reach the top 10 search results. That's a *prediction, not real data* — and it's labelled that way everywhere — but a calibrated guess still tells you something the rubric inspectors can't: *would this actually work?*

**It proposes its own fixes.** Once a week, a meta-agent reads the whole eval history, finds the one most systematic problem, and opens a pull request with a single fix — a prompt tweak, a tightened rubric, a new check. A human reviews and merges it. After 20 runs, the factory measures whether the change actually helped — and if it clearly *hurt*, it opens an automatic revert. The improvement loop closes in both directions.

**And it can't cheat.** This is the hard part. An agent told to "improve the scores" will, left unchecked, just weaken the inspectors. So the meta-agent is boxed in: it can only edit a short allowlist of files (never the graders, never the test box), it never even *sees* the inspectors' instructions when it writes a fix (so it can't write to the test instead of to the work), and six separate guards run on every proposal it makes — checking that it didn't loosen a rubric, didn't add a do-nothing inspector, didn't touch the sealed test box. The guards run from *trusted* copies of themselves, so the meta-agent can't disable its own guards. The full design is in [**`SELF_IMPROVEMENT.md`**](./SELF_IMPROVEMENT.md).

The **Learning Curve** page on the dashboard shows it all in one chart: brief quality over time, with a marker for every meta-agent change that merged along the way.

---

## Try it yourself

You need an [Anthropic API key](https://console.anthropic.com/) (a few dollars goes a long way). Optionally, a [DataForSEO](https://dataforseo.com/) account if you want real keyword data instead of LLM estimates.

**Easiest path — Docker:**

```bash
git clone https://github.com/lstrycharz/geoquery && cd geoquery
cp .env.example .env       # then paste your ANTHROPIC_API_KEY into .env
docker compose run --rm geoquery brief \
  --company "Notion" --market "B2B SaaS knowledge management"
```

**If you have Python locally** (3.13+ on macOS for the vector-database support):

```bash
git clone https://github.com/lstrycharz/geoquery && cd geoquery
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[semantic,web,report,mcp,dashboard,dev]"
cp .env.example .env       # paste your ANTHROPIC_API_KEY
geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

The agent will print a live commentary as it works (one line per stage), then a path to the finished brief.

**To run the dashboard locally** (against your own runs instead of the cloud demo data):

```bash
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501` with all six pages.

---

## Other things it can do

- `geoquery brief … --sitemap https://yoursite.com/sitemap.xml` — when you point it at your real sitemap, the brief's "link to these other pages on your site" suggestions are grounded in actual URLs from your site instead of LLM-imagined ones.
- `geoquery runs` — list every past run with its cost.
- `geoquery show <run-id>` — inspect what each stage of a past run did, what it cost, and how long it took.
- `geoquery feedback <run-id> --edited path/to/your-edited-brief.md` — once you've edited a brief by hand, this captures the change. Next time you ask for a brief in a similar market, the agent will see your preferred angle and try harder to match it.
- `geoquery eval-golden` — runs the agent against a fixed set of test inputs and grades the output. Useful when you've tweaked the prompts and want to make sure you didn't break anything.
- `pytest -m regression_smoke` — runs the 5-case smoke test box (~7 seconds, $0).
- `pytest -m regression_full` — runs the full 30-case test box (~30 seconds, $0).

It can also be used from inside Claude Desktop or Claude Code as a tool — see [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the MCP setup.

---

## For engineers reading the code

Three write-ups cover everything:
- [**`ARCHITECTURE.md`**](./ARCHITECTURE.md) — the agent itself: six layers (skills, tools, evals, guardrails, memory, feedback), seven skills, five tools, two interfaces (CLI + MCP).
- [**`EVALS.md`**](./EVALS.md) — the trust layer: four eval layers (deterministic + LLM-judge + regression suite + production monitoring), the CI regression gate, the Streamlit dashboard.
- [**`SELF_IMPROVEMENT.md`**](./SELF_IMPROVEMENT.md) — the self-improvement layer: the four learning mechanisms, the meta-agent, and the nine-part reward-hacking defense that stops it from gaming its own evals.

Built incrementally — v1 in 19 commits, v2 in 12 more, v3 in 11 chunks. Every commit leaves the repo in a working state. Tests run in ~11 seconds and cost $0.

```bash
pytest -q     # default suite — 290 tests, includes the 5 regression smoke cases
ruff check .  # lint
```

### Regression gate

Every PR runs the regression suite via [`.github/workflows/regression.yml`](./.github/workflows/regression.yml): the default pytest pass (smoke tier, 5 cases) plus the full tier (25 cases). Both replay recorded cassettes — deterministic, no API spend.

Cassettes are keyed by `sha256(system_prompt + user_message + model)`, so prompt edits force a "stale cassette" failure that surfaces in a per-PR comment with the per-case pass/fail diff. Re-record locally with `pytest -m regression_record` (free) or `pytest -m regression_record_live` (real Anthropic, ~$0.50/case).

The gate is already wired up on this repo via GitHub Rulesets. If you fork, set it up under Settings → Rules → Rulesets → "Require status checks" → add `regression`.

---

## License

MIT.
