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
from typing import Protocol

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
    ) -> None:
        embedding = self.embedder.embed(self._signature(market, icp_summary, angle))
        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedder returned {len(embedding)}-dim vector; expected {EMBEDDING_DIM}"
            )
        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO briefs (run_id, market, icp_summary, angle, brief_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, market, icp_summary, angle, brief_path, _now()),
            )
            rowid = cur.lastrowid
            conn.execute(
                "INSERT INTO brief_vec (rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize_vector(embedding)),
            )

    def find_similar(
        self, *, market: str, icp_summary: str, angle_hint: str = "", k: int = 3
    ) -> list[SimilarBrief]:
        embedding = self.embedder.embed(self._signature(market, icp_summary, angle_hint))
        with _connect(self.db_path) as conn:
            # If the store is empty, sqlite-vec's KNN raises; return [] cleanly.
            count = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
            if count == 0:
                return []
            rows = conn.execute(
                """
                SELECT briefs.run_id, briefs.market, briefs.icp_summary, briefs.angle,
                       briefs.brief_path, vec.distance
                FROM brief_vec vec
                JOIN briefs ON briefs.rowid = vec.rowid
                WHERE vec.embedding MATCH ?
                  AND k = ?
                ORDER BY vec.distance
                """,
                (_serialize_vector(embedding), k),
            ).fetchall()
        return [
            SimilarBrief(
                run_id=r["run_id"],
                market=r["market"],
                icp_summary=r["icp_summary"],
                angle=r["angle"],
                brief_path=r["brief_path"],
                distance=float(r["distance"]),
            )
            for r in rows
        ]


def _serialize_vector(vec: list[float]) -> bytes:
    """sqlite-vec accepts the raw little-endian f32 byte string."""
    import struct

    return struct.pack(f"{len(vec)}f", *vec)
