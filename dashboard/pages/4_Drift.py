"""Drift page — 7-day rolling pass rate per skill + judge-vs-human divergence."""

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
from evals.production import (  # noqa: E402
    DEFAULT_DRIFT_THRESHOLD,
    compute_drift_windows,
    compute_judge_human_divergence,
)

st.set_page_config(page_title="GEOQuery · Drift", layout="wide")
st.title("Drift — last 7 days vs prior 7 days")
st.caption(
    "Drift fires when a skill's pass-rate drops by ≥ 10 points vs the prior "
    "week (configurable). Small-N skills (<5 invocations per window) are "
    "marked but never trigger the banner — to avoid noise from rare paths."
)

db_path = resolve_db_path()
windows = compute_drift_windows(db_path)

if not windows:
    st.info("No skill invocations in the last 14 days.")
    st.stop()

drifting = [w for w in windows if w.drift_detected]
if drifting:
    skills = ", ".join(w.skill_name for w in drifting)
    st.error(
        f"⚠️ Drift detected in {len(drifting)} skill(s): **{skills}**. "
        f"Threshold: Δ ≤ {DEFAULT_DRIFT_THRESHOLD:+.0%}."
    )
else:
    st.success("No drift detected.")

# ---------------------------------------------------------------------------
# Pass-rate comparison table
# ---------------------------------------------------------------------------

st.subheader("Per-skill pass-rate windows")
df = pd.DataFrame(
    [
        {
            "skill": w.skill_name,
            "current (last 7d)": f"{w.current_pass_rate:.0%}",
            "current n": w.current_n,
            "prior (prior 7d)": f"{w.prior_pass_rate:.0%}",
            "prior n": w.prior_n,
            "Δ": f"{w.delta:+.0%}",
            "drift?": "yes" if w.drift_detected else "—",
        }
        for w in windows
    ]
)
st.dataframe(df, use_container_width=True, hide_index=True)

# Bar chart of deltas, sorted worst-first.
chart_df = pd.DataFrame(
    [{"skill": w.skill_name, "delta": w.delta * 100} for w in windows]
).sort_values("delta")
st.bar_chart(chart_df.set_index("skill")["delta"])

# ---------------------------------------------------------------------------
# Judge-vs-human divergence (chunk 7's review queue feeds this)
# ---------------------------------------------------------------------------

st.subheader("Judge ↔ human divergence (last 7 days)")
div = compute_judge_human_divergence(db_path)
if div.total_reviewed == 0:
    st.info(
        "No human reviews submitted in the last 7 days. Visit the **Review Queue** "
        "page to rate sampled runs — this surface lights up once data lands."
    )
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Reviewed", div.total_reviewed)
    col2.metric("Divergence rate", f"{div.divergence_rate:.0%}")
    col3.metric("Judges passed, human failed", div.judge_pass_human_fail)
    col4.metric("Judges failed, human passed", div.judge_fail_human_pass)
    if div.divergence_rate > 0.05:
        st.warning(
            "Divergence rate > 5%. One of the judges may need rubric recalibration — "
            "review the per-dim ratings in the Review Queue to find the offender."
        )
