from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from .common import now_iso

DEFAULT_DEDUP_THRESHOLD = 0.9
DEFAULT_SEMANTIC_DEDUP_THRESHOLD = 0.985


@dataclass
class DuplicateMatch:
    duplicate_of_chunk_id: str
    similarity: float
    reason: str


def normalize_for_dedup(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    normalized = re.sub(r"\[locator:[^\]]+\]", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    return normalized


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_dedup(text).encode("utf-8", errors="ignore")).hexdigest()


def char_ngrams(normalized: str, size: int = 4) -> set[str]:
    if not normalized:
        return set()
    if len(normalized) <= size:
        return {normalized}
    return {normalized[idx : idx + size] for idx in range(0, len(normalized) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(x * y for x, y in zip(left, right))
    left_norm = sum(x * x for x in left) ** 0.5
    right_norm = sum(x * x for x in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def compact_knowledge_point(text: str, max_chars: int = 80) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    point = lines[0]
    if len(point) < 12 and len(lines) > 1:
        point = f"{point} {lines[1]}"
    return point[:max_chars]


def find_duplicate_chunk(
    conn: sqlite3.Connection,
    *,
    text: str,
    layer: str,
    threshold: float = DEFAULT_DEDUP_THRESHOLD,
    embedding: list[float] | None = None,
    semantic_threshold: float = DEFAULT_SEMANTIC_DEDUP_THRESHOLD,
) -> DuplicateMatch | None:
    normalized = normalize_for_dedup(text)
    if len(normalized) < 24:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
    exact = conn.execute(
        """
        SELECT chunk_id FROM chunk_fingerprints
        WHERE text_hash = ? AND layer = ?
        LIMIT 1
        """,
        (digest, layer),
    ).fetchone()
    if exact:
        return DuplicateMatch(exact["chunk_id"], 1.0, "exact_normalized_text")

    length = len(normalized)
    low = max(0, int(length * 0.82))
    high = int(length * 1.18) + 1
    needle = char_ngrams(normalized)
    best: tuple[str, float] | None = None
    rows = conn.execute(
        """
        SELECT chunk_id, normalized_text
        FROM chunk_fingerprints
        WHERE layer = ?
          AND LENGTH(normalized_text) BETWEEN ? AND ?
        ORDER BY created_at DESC
        LIMIT 600
        """,
        (layer, low, high),
    ).fetchall()
    for row in rows:
        score = jaccard(needle, char_ngrams(row["normalized_text"]))
        if score >= threshold and (best is None or score > best[1]):
            best = (row["chunk_id"], score)
    if best:
        return DuplicateMatch(best[0], round(best[1], 4), "near_duplicate_ngrams")
    if embedding:
        rows = conn.execute(
            """
            SELECT id, embedding_json
            FROM chunks
            WHERE layer = ?
              AND embedding_json IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1200
            """,
            (layer,),
        ).fetchall()
        semantic_best: tuple[str, float] | None = None
        for row in rows:
            try:
                existing = [float(value) for value in json.loads(row["embedding_json"])]
            except Exception:
                continue
            score = cosine(embedding, existing)
            if score >= semantic_threshold and (semantic_best is None or score > semantic_best[1]):
                semantic_best = (row["id"], score)
        if semantic_best:
            return DuplicateMatch(semantic_best[0], round(semantic_best[1], 4), "semantic_embedding")
    return None


def record_chunk_fingerprint(
    conn: sqlite3.Connection,
    *,
    chunk_id: str,
    source_id: str,
    layer: str,
    text: str,
    knowledge_key: str | None = None,
) -> None:
    normalized = normalize_for_dedup(text)
    if len(normalized) < 24:
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO chunk_fingerprints
        (chunk_id, source_id, layer, text_hash, normalized_text, knowledge_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            source_id,
            layer,
            hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest(),
            normalized,
            knowledge_key or compact_knowledge_point(text),
            now_iso(),
        ),
    )


def backfill_missing_fingerprints(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT c.id, c.source_id, c.layer, c.text
        FROM chunks c
        LEFT JOIN chunk_fingerprints fp ON fp.chunk_id = c.id
        WHERE fp.chunk_id IS NULL
        """
    ).fetchall()
    for row in rows:
        record_chunk_fingerprint(
            conn,
            chunk_id=row["id"],
            source_id=row["source_id"],
            layer=row["layer"],
            text=row["text"],
        )
    conn.commit()
    return len(rows)


def audit_duplicate_fingerprints(conn: sqlite3.Connection) -> dict[str, Any]:
    exact = conn.execute(
        """
        SELECT layer, text_hash, COUNT(*) AS n, GROUP_CONCAT(chunk_id) AS chunk_ids
        FROM chunk_fingerprints
        GROUP BY layer, text_hash
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        LIMIT 100
        """
    ).fetchall()
    duplicate_records = conn.execute(
        """
        SELECT d.*, s.title AS source_title
        FROM ingest_duplicates d
        JOIN sources s ON s.id = d.source_id
        ORDER BY d.created_at DESC
        LIMIT 200
        """
    ).fetchall()
    return {
        "exact_duplicate_groups": [
            {
                "layer": row["layer"],
                "text_hash": row["text_hash"],
                "count": int(row["n"]),
                "chunk_ids": (row["chunk_ids"] or "").split(","),
            }
            for row in exact
        ],
        "blocked_duplicate_ingest_records": [
            {
                "source_id": row["source_id"],
                "source_title": row["source_title"],
                "candidate_id": row["candidate_id"],
                "duplicate_of_chunk_id": row["duplicate_of_chunk_id"],
                "layer": row["layer"],
                "path": row["path"],
                "similarity": row["similarity"],
                "reason": row["reason"],
                "created_at": row["created_at"],
                "sample_text": row["sample_text"],
            }
            for row in duplicate_records
        ],
    }


def record_duplicate_chunk(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    candidate_id: str,
    duplicate: DuplicateMatch,
    layer: str,
    path: str,
    title: str,
    locator: str,
    text: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO ingest_duplicates
        (id, source_id, candidate_id, duplicate_of_chunk_id, layer, path, title, locator,
         text_hash, similarity, reason, sample_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            source_id,
            candidate_id,
            duplicate.duplicate_of_chunk_id,
            layer,
            path,
            title,
            locator,
            text_hash(text),
            duplicate.similarity,
            duplicate.reason,
            text[:700],
            now_iso(),
        ),
    )


def summarize_duplicates(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT layer, reason, COUNT(*) AS n
        FROM ingest_duplicates
        WHERE source_id = ?
        GROUP BY layer, reason
        ORDER BY layer, reason
        """,
        (source_id,),
    ).fetchall()
    return {
        "total": sum(int(row["n"]) for row in rows),
        "by_layer_reason": [
            {"layer": row["layer"], "reason": row["reason"], "count": int(row["n"])}
            for row in rows
        ],
    }


def knowledge_points_from_output(output: dict[str, Any]) -> list[str]:
    points: list[str] = []
    for item in output.get("items") or []:
        if not isinstance(item, dict):
            continue
        raw_points = item.get("knowledge_points") or []
        if isinstance(raw_points, str):
            raw_points = [raw_points]
        if isinstance(raw_points, list):
            points.extend(str(point).strip() for point in raw_points if str(point).strip())
    return points


def normalized_point_set(points: list[str]) -> set[str]:
    return {normalize_for_dedup(point) for point in points if normalize_for_dedup(point)}


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)
