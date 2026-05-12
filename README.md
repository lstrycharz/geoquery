# GEO Query → Content Brief Agent

**You type two things in. Ten minutes later you get a complete article plan out.**

```
$ geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

Out comes a finished brief that a writer can use to draft the article: who it's for, the specific angle to take, what sections to write, what to cover in each one, what sources to cite, how long it should be, and which pages on your own site to link to.

It costs about **30 to 60 cents** per brief and takes **5 to 10 minutes**. There are [eight real examples](./briefs/) in the repo across very different industries — knowledge software, payments, beauty, outdoor apparel, and more — that show what you actually get.

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

**If you're trying to learn how to build agents that aren't black boxes,** the repo is meant to be read. The code is small (a few hundred lines per layer), every architectural choice is named, and [`ARCHITECTURE.md`](./ARCHITECTURE.md) explains *why* each one was made.

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
pip install -e ".[semantic,web,report,mcp,dev]"
cp .env.example .env       # paste your ANTHROPIC_API_KEY
geoquery brief --company "Notion" --market "B2B SaaS knowledge management"
```

The agent will print a live commentary as it works (one line per stage), then a path to the finished brief.

---

## Other things it can do

- `geoquery brief … --sitemap https://yoursite.com/sitemap.xml` — when you point it at your real sitemap, the brief's "link to these other pages on your site" suggestions are grounded in actual URLs from your site instead of LLM-imagined ones.
- `geoquery runs` — list every past run with its cost.
- `geoquery show <run-id>` — inspect what each stage of a past run did, what it cost, and how long it took.
- `geoquery feedback <run-id> --edited path/to/your-edited-brief.md` — once you've edited a brief by hand, this captures the change. Next time you ask for a brief in a similar market, the agent will see your preferred angle and try harder to match it.
- `geoquery eval-golden` — runs the agent against a fixed set of test inputs and grades the output. Useful when you've tweaked the prompts and want to make sure you didn't break anything.

It can also be used from inside Claude Desktop or Claude Code as a tool — see [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the MCP setup.

---

## For engineers reading the code

The full architecture write-up is in [**`ARCHITECTURE.md`**](./ARCHITECTURE.md). Short version: six layers (skills, tools, evals, guardrails, memory, feedback), seven skills, five tools, two interfaces (CLI + MCP), built incrementally over 19 commits each leaving the repo in a working state. Every layer has tests. ~130 of them at v2. They run in ~10 seconds and cost $0.

```bash
pytest -q     # default suite (~130 tests, includes the 5 regression smoke cases), $0
ruff check .  # lint
```

The v2 eval framework is documented in [**`EVALS.md`**](./EVALS.md): four-layer eval system (deterministic + LLM-judge + regression suite + production monitoring), a CI regression gate, and a Streamlit dashboard.

### Regression gate

Every PR runs the regression suite via [`.github/workflows/regression.yml`](./.github/workflows/regression.yml): the default pytest pass (smoke tier, 5 cases) plus the full tier (25 cases). Both replay recorded cassettes — deterministic, no API spend. Cassettes are keyed by `sha256(system_prompt + user_message + model)`, so prompt edits force a "stale cassette" failure that surfaces in a per-PR comment with the per-case pass/fail diff. Re-record locally with `pytest -m regression_record` (free) or `pytest -m regression_record_live` (real Anthropic, ~$0.50/case).

To make the gate blocking, set up branch protection on `main`:

1. GitHub → repo Settings → Branches → "Add branch protection rule"
2. Branch name pattern: `main`
3. Check "Require status checks to pass before merging"
4. Search for and select `regression / regression`
5. Save

---

## License

MIT.
