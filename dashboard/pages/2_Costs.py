"""Costs page — distribution of per-run cost + p50/p95."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.app import resolve_db_path
from dashboard.data import cost_per_run

st.set_page_config(page_title="GEOQuery · Costs", layout="wide")
st.title("Costs — per-run distribution")

db_path = resolve_db_path()
st.caption(f"Reading from `{db_path.name}`")

rows = cost_per_run(db_path)
if not rows:
    st.info("No completed runs yet.")
    st.stop()

df = pd.DataFrame(rows)
costs = df["total_cost_usd"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Runs", f"{len(df)}")
col2.metric("Median (p50)", f"${costs.median():.4f}")
col3.metric("p95", f"${costs.quantile(0.95):.4f}")
col4.metric("Max", f"${costs.max():.4f}")

st.subheader("Histogram (USD per run)")
# Streamlit's bar_chart over a 12-bucket histogram is clearer than the
# native line/area chart for a long-tailed cost distribution.
buckets = pd.cut(costs, bins=12)
counts = buckets.value_counts().sort_index()
counts.index = counts.index.map(lambda iv: f"${iv.left:.4f} - ${iv.right:.4f}")
counts = counts.rename("runs")
st.bar_chart(counts)

st.subheader("Cost over time")
df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
st.line_chart(df.set_index("started_at")["total_cost_usd"])

st.subheader("Top 10 most expensive runs")
top = df.sort_values("total_cost_usd", ascending=False).head(10)[
    ["id", "company", "market", "total_cost_usd", "started_at"]
]
st.dataframe(top, use_container_width=True, hide_index=True)
