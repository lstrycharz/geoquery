"""Pure data helpers for the Streamlit dashboard.

This module deliberately has no Streamlit imports. Pages call these functions
to fetch dicts/rows and then render them; the helpers own the SQL. Two reasons:
unit-tested boundary, and a clean swap-out if a future page wants pandas / a
chart that needs raw rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def recent_runs(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent `limit` rows from the runs table, newest first.

    Parameterized — `limit` always travels as a query parameter, never spliced
    into the SQL string.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, started_at, ended_at, company, market, status, "
            "total_cost_usd, brief_path "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
