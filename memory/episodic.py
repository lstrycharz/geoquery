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

    # ------------------------------------------------------------------
    # Meta-agent proposals (v3 chunk 2)
    # ------------------------------------------------------------------

    def record_meta_proposal(
        self,
        *,
        target_pattern: str,
        change_type: str,
        hypothesis: str,
        branch: str | None = None,
        pr_number: int | None = None,
        status: str = "proposed",
        created_at: str | None = None,
    ) -> int:
        """Append a meta-agent proposal. `created_at` defaults to now; tests
        override it to exercise the analyze() cooldown window."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO meta_proposals "
                "(created_at, target_pattern, change_type, hypothesis, branch, "
                " pr_number, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    created_at or _now(),
                    target_pattern,
                    change_type,
                    hypothesis,
                    branch,
                    pr_number,
                    status,
                ),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # Outcome predictions (v3 chunk 7)
    # ------------------------------------------------------------------

    def record_outcome_prediction(
        self,
        *,
        run_id: str,
        predicted_top10: bool,
        confidence: float,
        reasoning: str,
        model: str,
        created_at: str | None = None,
    ) -> int:
        """Append a (simulated) 30-day outcome prediction for a run's brief."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO outcome_predictions "
                "(run_id, predicted_top10, confidence, reasoning, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    1 if predicted_top10 else 0,
                    confidence,
                    reasoning,
                    model,
                    created_at or _now(),
                ),
            )
            return int(cur.lastrowid)

    def get_outcome_prediction(self, run_id: str) -> dict[str, Any] | None:
        """The most recent outcome prediction for a run, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM outcome_predictions WHERE run_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["predicted_top10"] = bool(record["predicted_top10"])
        return record

    def runs_pending_outcome_prediction(self) -> list[dict[str, Any]]:
        """Completed runs that have a drafted brief and no outcome prediction yet.

        Each row carries a `sampled` flag (True when the run was picked by the
        human-review sampler) so the batch command can score the sampled subset
        plus any already-high-scoring run, not every brief — Opus is expensive.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT r.*, (hr.id IS NOT NULL) AS sampled "
                "FROM runs r "
                "LEFT JOIN human_reviews hr ON hr.run_id = r.id "
                "WHERE r.status = 'completed' "
                "  AND r.id NOT IN (SELECT run_id FROM outcome_predictions) "
                "  AND r.id IN ("
                "      SELECT run_id FROM skill_invocations "
                "      WHERE skill_name = 'draft_content_brief') "
                "GROUP BY r.id "
                "ORDER BY r.started_at DESC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["sampled"] = bool(record["sampled"])
            out.append(record)
        return out

    # ------------------------------------------------------------------
    # Escalations (v3 chunk 6)
    # ------------------------------------------------------------------

    def record_escalation(
        self,
        *,
        run_id: str,
        skill_name: str,
        attempt_failures: list[list[str]],
        final_output_json: str | None,
        escalated_at: str | None = None,
    ) -> int:
        """Append an escalation row — a skill that exhausted its retry cap."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO escalations "
                "(run_id, skill_name, attempts_json, final_output_json, escalated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    skill_name,
                    json.dumps(attempt_failures),
                    final_output_json,
                    escalated_at or _now(),
                ),
            )
            return int(cur.lastrowid)

    def get_escalations(self, run_id: str) -> list[dict[str, Any]]:
        """Escalations for a run, with `attempt_failures` decoded to a list."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM escalations WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["attempt_failures"] = json.loads(record.pop("attempts_json"))
            out.append(record)
        return out

    # ------------------------------------------------------------------
    # Winning patterns (v3 chunk 5)
    # ------------------------------------------------------------------

    def record_winning_patterns(
        self,
        *,
        briefs_analyzed: int,
        min_eval_score: float,
        patterns: list[str],
        extracted_at: str | None = None,
    ) -> int:
        """Append one winning-patterns extraction. `extracted_at` defaults to
        now; tests override it to exercise the staleness signal."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO winning_patterns "
                "(extracted_at, briefs_analyzed, min_eval_score, patterns_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    extracted_at or _now(),
                    briefs_analyzed,
                    min_eval_score,
                    json.dumps(patterns),
                ),
            )
            return int(cur.lastrowid)

    def get_latest_winning_patterns(self) -> dict[str, Any] | None:
        """The most recent extraction, with `patterns` decoded to list[str].
        None when nothing has been extracted yet."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM winning_patterns ORDER BY extracted_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["patterns"] = json.loads(record.pop("patterns_json"))
        return record


# v3 chunk 8: the (simulated) outcome signal informs the blended eval score
# but doesn't dominate the real judge-pass-rate signal.
_OUTCOME_WEIGHT = 0.4


def blend_eval_score(
    judge_score: float,
    *,
    predicted_top10: bool | None = None,
    confidence: float | None = None,
) -> float:
    """Blend the judge-pass-rate score with the (simulated) predicted-outcome
    signal (v3 chunk 8, Mechanism 3 feedback loop).

    With no prediction the judge score stands unchanged. With one, the
    prediction becomes a 0-1 "likely to succeed" score (`confidence` when
    top-10 is predicted, `1 - confidence` otherwise) and is mixed in at
    `_OUTCOME_WEIGHT` — informative, but the real judge signal stays primary.
    """
    if predicted_top10 is None or confidence is None:
        return judge_score
    outcome_score = confidence if predicted_top10 else (1.0 - confidence)
    return (1.0 - _OUTCOME_WEIGHT) * judge_score + _OUTCOME_WEIGHT * outcome_score


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
