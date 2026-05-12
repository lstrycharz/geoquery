# Deploy the dashboard to Streamlit Cloud (free tier)

Streamlit Cloud reads from a GitHub repo and serves a Streamlit app at a
`*.streamlit.app` URL. Free tier supports unlimited public apps with
reasonable CPU/RAM. This doc covers a one-time setup; after that, every
push to `main` redeploys automatically.

## Prerequisites

- Public GitHub repo containing this codebase (`geoquery`).
- `data/episodic.demo.db` committed under `data/`. The gitignore re-includes
  it specifically so Cloud sees a populated DB on cold-boot. Regenerate with
  `python scripts/build_demo_db.py` if you want fresh seed data.
- A free [share.streamlit.io](https://share.streamlit.io) account.

## Steps

1. Sign in to share.streamlit.io with GitHub.
2. Click **New app**.
3. Connect the GitHub repo + branch `main`.
4. Set **Main file path** to `dashboard/app.py`.
5. Set **Python version** to `3.13`.
6. Click **Deploy**.

Cloud auto-detects `pyproject.toml` and `pip install -e .` runs in the
container. For the dashboard pages to import, we need the `[dashboard]`
extra to also install. Add a `.streamlit/requirements.txt` that mirrors
the extra (or, if Cloud is picking up the wheel, the deps come along
automatically). Smallest path: drop a one-line `requirements.txt` at
the repo root with `.[dashboard]` and Cloud follows the standard pip
install.

## Verify the deploy

Hit the `*.streamlit.app` URL and check:

- Landing page shows the **Recent Runs** table populated from the demo DB.
- Sidebar has 5 pages: Evals / Costs / Tools / Drift / Review_Queue.
- Each page renders without exceptions.
- If you seeded the demo with a drifting skill, the landing-page banner
  fires.

## Common gotchas

- **Cold-boot time** ≈ 60s on free tier. First visit after inactivity is
  slow; subsequent visits are fast.
- **The dashboard cannot post Slack alerts from Cloud** unless you set
  `SLACK_WEBHOOK_URL` in the app's secrets manager. The Cloud sandbox
  has outbound HTTP available; the limitation is just credential plumbing.
- **`data/episodic.db` is gitignored** by design — Cloud only ever sees
  the demo DB. If you want Cloud to show real production data, set up a
  separate pipeline (e.g., push the prod DB to S3 + read from there).
- **Multipage discovery** requires `dashboard/pages/` to exist with
  numbered filenames (`1_Evals.py`, `2_Costs.py`, etc.). Streamlit picks
  them up by filename — no manual registration.

## Updating the live demo data

```bash
python scripts/build_demo_db.py
git add data/episodic.demo.db
git commit -m "demo: refresh dashboard seed data"
git push
```

Cloud redeploys within a minute. The seed is deterministic
(`random.Random(42)`), so the same script always produces the same DB
unless you edit the script itself.
