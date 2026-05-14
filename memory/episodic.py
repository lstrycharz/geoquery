"""Episodic memory — SQLite write log of every run and every skill invocation.

Append-only, parameterized queries, schema-versioned rows.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RunRecord:
    id: str
    started_at: str
    company: str
    market: str
    status: str = "in_progress"
    ended_at: str | None = None
    total_cost_usd: float = 0.0
    brief_path: str | None = None


@dataclass
class SkillInvocationRecord:
    run_id: str
    skill_name: str
    attempt: int
    model: str
    input_json: str
    started_at: str
    output_json: str | None = None
    eval_passed: bool | None = None
    eval_details_json: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int | None = None


class EpisodicMemory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)

    def start_run(self, company: str, market: str) -> RunRecord:
        record = RunRecord(id=str(uuid.uuid4()), started_at=_now(), company=company, market=market)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, started_at, company, market, status, total_cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (record.id, record.started_at, record.company, record.market, record.status, 0.0),
            )
        return record

    def finish_run(
        self,
        run_id: str,
        status: str,
        total_cost_usd: float,
        brief_path: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, ended_at = ?, total_cost_usd = ?, brief_path = ? "
                "WHERE id = ?",
                (status, _now(), total_cost_usd, brief_path, run_id),
            )

    def log_skill_invocation(self, record: SkillInvocationRecord) -> None:
        eval_passed_int: int | None = (
            None if record.eval_passed is None else (1 if record.eval_passed else 0)
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_invocations "
                "(run_id, skill_name, attempt, model, input_json, output_json, "
                " eval_passed, eval_details_json, input_tokens, output_tokens, "
                " cost_usd, duration_ms, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.skill_name,
                    record.attempt,
                    record.model,
                    record.input_json,
                    record.output_json,
                    eval_passed_int,
                    record.eval_details_json,
                    record.input_tokens,
                    record.output_tokens,
                    record.cost_usd,
                    record.duration_ms,
                    record.started_at,
                ),
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_invocations(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_invocations WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def compute_run_eval_score(self, run_id: str) -> float:
        """v3 chunk 1: a run's 0-1 eval composite - the fraction of its skill
        invocations that passed *cleanly* (eval_passed=1 AND no failure entries,
        advisory ones included). A run where every judge was happy scores 1.0;
        advisory judge grumbles on the drafter pull it down. Skills with no
        evaluators count as clean. Returns 1.0 (neutral) when nothing was
        evaluated.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT eval_passed, eval_details_json FROM skill_invocations "
                "WHERE run_id = ? AND eval_passed IS NOT NULL",
                (run_id,),
            ).fetchall()
        if not rows:
            return 1.0
        clean = sum(
            1 for r in rows if r["eval_passed"] == 1 and (r["eval_details_json"] in (None, "[]"))
        )
        return clean / len(rows)

    def log_human_edit(
        self,
        *,
        run_id: str,
        original_brief_path: str,
        edited_brief_path: str,
        diff_summary: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO human_edits "
                "(run_id, original_brief_path, edited_brief_path, diff_summary, captured_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, original_brief_path, edited_brief_path, diff_summary, _now()),
            )

    def get_human_edits(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM human_edits WHERE run_id = ? ORDER BY captured_at ASC", (run_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Production sample stream (v2 chunk 7)
    # ------------------------------------------------------------------

    def start_human_review(self, *, run_id: str) -> int:
        """Mark a run as sampled for review. The row stays pending (reviewed_at
        NULL) until a human submits via the dashboard."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO human_reviews (run_id, sampled_at) VALUES (?, ?)",
                (run_id, _now()),
            )
            return int(cur.lastrowid)

    def record_human_review(
        self,
        *,
        review_id: int,
        rating_overall: int,
        ratings_by_dim: dict[str, int] | None = None,
        notes: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE human_reviews SET reviewed_at = ?, "
                "reviewer_rating_overall = ?, reviewer_ratings_by_dim = ?, "
                "reviewer_notes = ? WHERE id = ?",
                (
                    _now(),
                    rating_overall,
                    json.dumps(ratings_by_dim) if ratings_by_dim else None,
                    notes,
                    review_id,
                ),
            )

    def get_pending_reviews(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT hr.id, hr.run_id, hr.sampled_at, r.company, r.market, r.brief_path "
                "FROM human_reviews hr "
                "JOIN runs r ON r.id = hr.run_id "
                "WHERE hr.reviewed_at IS NULL "
                "ORDER BY hr.sampled_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_review(self, review_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM human_reviews WHERE id = ?", (review_id,)).fetchone()
        return dict(row) if row else None


def serialize_for_log(value: Any) -> str:
    """Best-effort JSON serialization for skill inputs/outputs."""
    try:
        return json.dumps(value, default=_json_default, ensure_ascii=False)
    except TypeError:
        return json.dumps({"_unserializable": repr(value)})


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)
