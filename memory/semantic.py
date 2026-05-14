"""Semantic memory — past briefs indexed for RAG injection into the drafter.

Stack: sqlite-vec for vector storage + fastembed (CPU ONNX, BAAI/bge-small-en-v1.5,
384-dim) for embeddings. No torch dependency; no external API call.

The drafter retrieves top-k similar past briefs (matched on
`market + icp_summary + angle`) before drafting a new one — both as
inspiration and as a "don't re-write what you already did" guardrail.

Tests inject a stub Embedder so they don't download the model.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Protocol

import sqlite_vec

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class FastembedEmbedder:
    """Default production embedder. Lazy-loads the model on first call."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model_name = model_name
        self._model = None  # type: ignore[var-annotated]

    def embed(self, text: str) -> list[float]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        vectors = list(self._model.embed([text]))
        return [float(x) for x in vectors[0].tolist()]


@dataclass(frozen=True)
class SimilarBrief:
    run_id: str
    market: str
    icp_summary: str
    angle: str
    brief_path: str
    distance: float
    # v3 chunk 1: score-aware memory. eval_score is the run's 0-1 eval composite;
    # section_skeleton is the brief's headings joined - enough to show the drafter
    # the *shape* of a high-scoring brief without injecting the full ~1.5k-token body.
    eval_score: float = 1.0
    section_skeleton: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


class SemanticMemory:
    def __init__(self, db_path: Path, embedder: Embedder | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder: Embedder = embedder or FastembedEmbedder()
        self._init_schema()

    # v3 chunk 1: columns added after the original v2 `briefs` table. Applied as
    # additive ALTER TABLE migrations so pre-v3 semantic.db files keep working.
    _V3_COLUMNS: ClassVar[dict[str, str]] = {
        "eval_score": "REAL NOT NULL DEFAULT 1.0",
        "eval_details_json": "TEXT",
        "section_skeleton": "TEXT NOT NULL DEFAULT ''",
    }

    def _init_schema(self) -> None:
        with _connect(self.db_path) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS briefs (
                    rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id         TEXT NOT NULL,
                    market         TEXT NOT NULL,
                    icp_summary    TEXT NOT NULL,
                    angle          TEXT NOT NULL,
                    brief_path     TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS brief_vec
                USING vec0(embedding float[{EMBEDDING_DIM}]);
                """
            )
            existing = {row[1] for row in conn.execute("PRAGMA table_info(briefs)")}
            for name, decl in self._V3_COLUMNS.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE briefs ADD COLUMN {name} {decl}")

    @staticmethod
    def _signature(market: str, icp_summary: str, angle: str) -> str:
        return f"market: {market}\nicp: {icp_summary}\nangle: {angle}"

    def index_brief(
        self,
        *,
        run_id: str,
        market: str,
        icp_summary: str,
        angle: str,
        brief_path: str,
        eval_score: float = 1.0,
        eval_details_json: str | None = None,
        section_skeleton: str = "",
    ) -> None:
        embedding = self.embedder.embed(self._signature(market, icp_summary, angle))
        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedder returned {len(embedding)}-dim vector; expected {EMBEDDING_DIM}"
            )
        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO briefs (run_id, market, icp_summary, angle, brief_path, "
                "created_at, eval_score, eval_details_json, section_skeleton) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    market,
                    icp_summary,
                    angle,
                    brief_path,
                    _now(),
                    eval_score,
                    eval_details_json,
                    section_skeleton,
                ),
            )
            rowid = cur.lastrowid
            conn.execute(
                "INSERT INTO brief_vec (rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize_vector(embedding)),
            )

    def find_similar(
        self,
        *,
        market: str,
        icp_summary: str,
        angle_hint: str = "",
        k: int = 3,
        rank_by_eval_score: bool = False,
    ) -> list[SimilarBrief]:
        """Retrieve the k most relevant past briefs.

        Default: ranked by embedding distance (closest first).
        `rank_by_eval_score=True` (v3 chunk 1): pull a wider distance-candidate
        set, then re-rank it by eval_score (highest first, distance as
        tie-break) and return the top k. This is how the drafter gets
        *high-performing* similar briefs as few-shot examples rather than just
        *nearby* ones.
        """
        embedding = self.embedder.embed(self._signature(market, icp_summary, angle_hint))
        with _connect(self.db_path) as conn:
            # If the store is empty, sqlite-vec's KNN raises; return [] cleanly.
            count = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
            if count == 0:
                return []
            # When re-ranking by score, fetch a wider candidate pool so the
            # re-rank has room to surface a high-scorer that wasn't the single
            # closest by distance.
            fetch_k = min(k * 4, count) if rank_by_eval_score else min(k, count)
            rows = conn.execute(
                """
                SELECT briefs.run_id, briefs.market, briefs.icp_summary, briefs.angle,
                       briefs.brief_path, briefs.eval_score, briefs.section_skeleton,
                       vec.distance
                FROM brief_vec vec
                JOIN briefs ON briefs.rowid = vec.rowid
                WHERE vec.embedding MATCH ?
                  AND k = ?
                ORDER BY vec.distance
                """,
                (_serialize_vector(embedding), fetch_k),
            ).fetchall()
        briefs = [
            SimilarBrief(
                run_id=r["run_id"],
                market=r["market"],
                icp_summary=r["icp_summary"],
                angle=r["angle"],
                brief_path=r["brief_path"],
                distance=float(r["distance"]),
                eval_score=float(r["eval_score"]),
                section_skeleton=r["section_skeleton"] or "",
            )
            for r in rows
        ]
        if rank_by_eval_score:
            # Highest eval_score first; closer distance breaks ties.
            briefs.sort(key=lambda b: (-b.eval_score, b.distance))
        return briefs[:k]

    def top_scoring_briefs(self, limit: int = 10) -> list[SimilarBrief]:
        """The globally highest-scoring indexed briefs, ranked by eval_score.

        Unlike `find_similar`, this isn't query-relative — it's the corpus the
        winning-patterns extractor (v3 chunk 5) distills structural patterns
        from. `distance` is 0.0 (not meaningful here)."""
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT run_id, market, icp_summary, angle, brief_path, "
                "eval_score, section_skeleton "
                "FROM briefs ORDER BY eval_score DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            SimilarBrief(
                run_id=r["run_id"],
                market=r["market"],
                icp_summary=r["icp_summary"],
                angle=r["angle"],
                brief_path=r["brief_path"],
                distance=0.0,
                eval_score=float(r["eval_score"]),
                section_skeleton=r["section_skeleton"] or "",
            )
            for r in rows
        ]


def _serialize_vector(vec: list[float]) -> bytes:
    """sqlite-vec accepts the raw little-endian f32 byte string."""
    import struct

    return struct.pack(f"{len(vec)}f", *vec)
