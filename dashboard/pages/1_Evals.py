"""Evals page — per-skill pass-rate trend over time."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.app import resolve_db_path
from dashboard.data import pass_rate_per_skill_per_day

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
