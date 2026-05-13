"""Evals page — per-skill pass-rate trend over time."""

from __future__ import annotations

import sys
from pathlib import Path

# Cloud's `streamlit run` puts the script dir on sys.path[0]; we need the repo
# root so `from dashboard.X import …` resolves. See dashboard/app.py for context.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.app import resolve_db_path  # noqa: E402
from dashboard.data import pass_rate_per_skill_per_day  # noqa: E402

st.set_page_config(page_title="GEOQuery · Evals", layout="wide")
st.title("Evals — per-skill pass rate over time")

db_path = resolve_db_path()
st.caption(f"Reading from `{db_path.name}`")

rows = pass_rate_per_skill_per_day(db_path)
if not rows:
    st.info("No skill invocations recorded yet.")
    st.stop()

df = pd.DataFrame(rows)
# A wide-format pivot makes a multi-series line chart trivial in Streamlit.
pivot = df.pivot_table(index="day", columns="skill_name", values="pass_rate", aggfunc="mean")
st.subheader("Pass rate by skill (1.0 = all evals passing)")
st.line_chart(pivot)

st.subheader("Per-skill totals")
totals = (
    df.groupby("skill_name").agg(total=("total", "sum"), passed=("passed", "sum")).reset_index()
)
totals["pass_rate"] = (totals["passed"] / totals["total"]).round(3)
st.dataframe(totals, use_container_width=True, hide_index=True)
