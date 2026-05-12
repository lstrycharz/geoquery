"""Streamlit dashboard for GEOQuery — reads episodic.db, never writes.

`data.py` owns the SQL (pure, testable). The `app.py` entrypoint and per-page
modules under `pages/` import those helpers and handle presentation only.
"""
