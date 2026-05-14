"""Learning Curve page — brief quality over run sequence, annotated with the
meta-agent PRs that merged along the way. The visible improvement curve is the
v3 deliverable."""

from __future__ import annotations

import sys
from pathlib import Path

# Cloud's `streamlit run` puts the script dir on sys.path[0]; we need the repo
# root so `from dashboard.X import …` resolves. See dashboard/app.py for context.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.app import resolve_db_path  # noqa: E402
from dashboard.data import brief_quality_trend_by_run  # noqa: E402

st.set_page_config(page_title="GEOQuery · Learning Curve", layout="wide")
st.title("Learning Curve — brief quality over time")
st.caption(
    "Quality is the mean of whichever signals exist per run: judge eval "
    "composite, (simulated) predicted outcome, and human review rating. "
    "Vertical markers are merged meta-agent PRs."
)

db_path = resolve_db_path()
st.caption(f"Reading from `{db_path.name}`")

trend = brief_quality_trend_by_run(db_path)
points = trend["points"]
markers = trend["meta_pr_markers"]

if not points:
    st.info("No completed runs yet — the learning curve needs run history.")
    st.stop()

df = pd.DataFrame(points)

# A 5-run rolling mean smooths the per-run noise without hiding the trend.
df["rolling_quality"] = df["quality"].rolling(window=5, min_periods=1).mean()

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=df["run_seq"],
        y=df["quality"],
        mode="markers",
        name="per-run quality",
        marker={"size": 6, "color": "#9aa0a6"},
        customdata=df[["company", "started_at"]],
        hovertemplate=(
            "run #%{x}<br>%{customdata[0]}<br>quality %{y:.2f}<br>%{customdata[1]}<extra></extra>"
        ),
    )
)
fig.add_trace(
    go.Scatter(
        x=df["run_seq"],
        y=df["rolling_quality"],
        mode="lines",
        name="5-run rolling mean",
        line={"width": 3, "color": "#1a73e8"},
    )
)

# Vertical annotation per merged meta-agent PR. Reverts are flagged red so a
# negative measurement is visible, not buried — the loop closes both ways.
for m in markers:
    reverted = m["status"] == "reverted"
    fig.add_vline(
        x=m["run_seq"] + 0.5,
        line_width=1.5,
        line_dash="dash",
        line_color="#d93025" if reverted else "#34a853",
    )
    fig.add_annotation(
        x=m["run_seq"] + 0.5,
        yref="paper",
        y=1.0,
        text=f"PR #{m['pr_number']}" + (" (reverted)" if reverted else ""),
        showarrow=False,
        textangle=-90,
        xanchor="left",
        font={"size": 10, "color": "#d93025" if reverted else "#34a853"},
    )

fig.update_layout(
    xaxis_title="run sequence",
    yaxis_title="brief quality (0-1)",
    yaxis_range=[0, 1.05],
    legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
    margin={"t": 40},
    height=480,
)
st.plotly_chart(fig, use_container_width=True)

col1, col2, col3 = st.columns(3)
col1.metric("Completed runs", f"{len(df)}")
col2.metric("Latest rolling quality", f"{df['rolling_quality'].iloc[-1]:.2f}")
col3.metric("Merged meta-agent PRs", f"{len(markers)}")

if markers:
    st.subheader("Merged meta-agent PRs")
    st.dataframe(
        pd.DataFrame(markers)[["pr_number", "target_pattern", "status", "merged_at"]],
        use_container_width=True,
        hide_index=True,
    )
