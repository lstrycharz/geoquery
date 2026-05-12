"""Tools page — skill failure rate (eval_passed=0 or NULL)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.app import resolve_db_path
from dashboard.data import skill_failure_rate

st.set_page_config(page_title="GEOQuery · Tools", layout="wide")
st.title("Skill failure rate")

st.caption(
    "Failures = invocations where `eval_passed = 0` OR `eval_passed IS NULL`. "
    "The latter covers skills that threw before eval ran (a tool fault) and "
    "legacy rows from pre-v2 runs."
)

db_path = resolve_db_path()
rows = skill_failure_rate(db_path)
if not rows:
    st.info("No skill invocations recorded yet.")
    st.stop()

df = pd.DataFrame(rows)
df["failure_rate_pct"] = (df["failure_rate"] * 100).round(2)
st.bar_chart(df.set_index("skill_name")["failure_rate_pct"])

st.subheader("Per-skill counts")
st.dataframe(
    df[["skill_name", "total", "failures", "failure_rate_pct"]],
    use_container_width=True,
    hide_index=True,
)
