"""Review queue — pending sampled runs awaiting a human rating.

The judges return advisory pass/fail; humans give a 1-5 overall rating plus
per-dimension ratings. The divergence between the two surfaces on chunk 8's
Drift page so we can flag judges whose rubrics need recalibration.
"""

from __future__ import annotations

import json
import sqlite3

import streamlit as st

from dashboard.app import resolve_db_path
from dashboard.data import judge_outcomes_for_run, pending_reviews

st.set_page_config(page_title="GEOQuery · Review Queue", layout="wide")
st.title("Review Queue — pending sampled runs")

db_path = resolve_db_path()
st.caption(f"Reading from `{db_path.name}`")

pending = pending_reviews(db_path)
if not pending:
    st.info(
        "Queue is empty. New samples land here automatically as runs complete "
        "(10% of runs by default; tune `SAMPLE_RATE` to change density)."
    )
    st.stop()

st.write(f"**{len(pending)} pending** — pick one to rate.")

# Pick mode: a select-box for the active review, then a per-dim form below.
# We avoid showing all reviews simultaneously to keep focus on one at a time.
options = {f"[{r['sampled_at'][:10]}] {r['company']} — {r['market']}": r for r in pending}
choice_label = st.selectbox("Pending reviews", list(options.keys()))
if not choice_label:
    st.stop()
chosen = options[choice_label]

st.divider()
st.subheader(f"{chosen['company']} — {chosen['market']}")
st.caption(
    f"run_id: `{chosen['run_id'][:8]}`  ·  "
    f"sampled_at: `{chosen['sampled_at']}`  ·  "
    f"cost: ${chosen['total_cost_usd']:.4f}"
)

# Show the brief if its file is reachable from the dashboard's working dir.
if chosen.get("brief_path"):
    from pathlib import Path

    brief_path = Path(chosen["brief_path"])
    if brief_path.is_file():
        with st.expander("Brief content", expanded=False):
            st.markdown(brief_path.read_text(encoding="utf-8"))
    else:
        st.caption(f"_Brief file `{chosen['brief_path']}` not found on this filesystem._")

st.subheader("What the judges said at run-time")
judge_rows = judge_outcomes_for_run(db_path, chosen["run_id"])
if judge_rows:
    rendered: list[dict] = []
    for jr in judge_rows:
        details = jr.get("eval_details_json")
        try:
            parsed = json.loads(details) if details else []
        except json.JSONDecodeError:
            parsed = [str(details)]
        rendered.append(
            {
                "skill": jr["skill_name"],
                "model": jr["model"],
                "eval_passed": jr["eval_passed"],
                "advisory_failures": parsed if parsed else "—",
            }
        )
    st.dataframe(rendered, use_container_width=True, hide_index=True)
else:
    st.caption("No skill invocations recorded for this run.")

st.subheader("Your rating")
with st.form(key=f"review_{chosen['review_id']}"):
    overall = st.slider(
        "Overall rating",
        min_value=1,
        max_value=5,
        value=4,
        help="1 = useless, 3 = workable, 5 = ship-ready",
    )
    col1, col2, col3 = st.columns(3)
    brand_voice = col1.slider("Brand voice", 1, 5, 4)
    intent_fit = col2.slider("Search-intent fit", 1, 5, 4)
    actionability = col3.slider("Actionability", 1, 5, 4)
    notes = st.text_area(
        "Notes (what would you change?)",
        placeholder="e.g. section 3 key_points are abstract — needs more concrete examples",
    )
    submitted = st.form_submit_button("Submit review")

if submitted:
    # Direct SQL update — keeps the Streamlit page free of `memory` imports
    # and lets us round-trip from a fresh-clone Cloud env where the package
    # might not be installed system-wide.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE human_reviews SET reviewed_at = datetime('now'), "
            "reviewer_rating_overall = ?, reviewer_ratings_by_dim = ?, "
            "reviewer_notes = ? WHERE id = ?",
            (
                overall,
                json.dumps(
                    {
                        "brand_voice": brand_voice,
                        "intent_fit": intent_fit,
                        "actionability": actionability,
                    }
                ),
                notes or None,
                chosen["review_id"],
            ),
        )
    st.success(f"Review {chosen['review_id']} saved. Reloading…")
    st.rerun()
