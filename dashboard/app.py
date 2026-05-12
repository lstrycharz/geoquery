"""Streamlit dashboard entrypoint — reads data/episodic.db, never writes.

Run locally:
    streamlit run dashboard/app.py

Reads from `data/episodic.db` by default; override with the env var
`GEOQUERY_EPISODIC_DB`. Falls back to the committed `data/episodic.demo.db`
when neither exists, so a fresh clone shows a populated UI on first launch.

This file is intentionally thin: SQL lives in `dashboard/data.py` so it can be
unit-tested without Streamlit. Future pages live under `dashboard/pages/`.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from dashboard.data import recent_runs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "episodic.db"
DEMO_DB = PROJECT_ROOT / "data" / "episodic.demo.db"


def resolve_db_path() -> Path:
    """Pick the DB to read from: env override > production DB > demo DB."""
    override = os.environ.get("GEOQUERY_EPISODIC_DB")
    if override:
        return Path(override)
    if DEFAULT_DB.is_file():
        return DEFAULT_DB
    return DEMO_DB


def _render_drift_banner(db_path: Path) -> None:
    """Top-of-dashboard banner that fires when any skill has regressed > 10
    points week-over-week. Cheap to compute (a single grouped aggregate),
    cheap to render — keeps drift visibility free even when the user never
    navigates to the Drift page."""
    try:
        from evals.production import compute_drift_windows
    except Exception:
        return
    try:
        windows = compute_drift_windows(db_path)
    except Exception:
        return
    drifting = [w for w in windows if w.drift_detected]
    if drifting:
        skills = ", ".join(w.skill_name for w in drifting)
        st.error(
            f"⚠️ Drift detected in {len(drifting)} skill(s): **{skills}**. "
            "See the **Drift** page for the per-skill window breakdown."
        )


def main() -> None:
    st.set_page_config(page_title="GEOQuery — Runs", layout="wide")
    st.title("GEOQuery — Recent Runs")
    db_path = resolve_db_path()
    st.caption(f"Reading from `{db_path.relative_to(PROJECT_ROOT)}`")
    if not db_path.is_file():
        st.warning(
            f"No episodic DB found at `{db_path}`. Run `geoquery brief …` once "
            "to populate it, or commit `data/episodic.demo.db` to ship a demo."
        )
        return
    _render_drift_banner(db_path)
    rows = recent_runs(db_path, limit=50)
    if not rows:
        st.info("No runs recorded yet. Run `geoquery brief …` to create one.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
