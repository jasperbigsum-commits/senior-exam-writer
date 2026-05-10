from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Callable

from .common import DEFAULT_EMBED_MODEL
from .llama_cpp_client import llama_embed
from .retrieval import load_vector

THRESHOLD_POLICY = {
    "blocked_duplicate": 0.98,
    "revise_required": 0.93,
    "pass_with_watch": 0.85,
}


def classify_similarity(score: float) -> str:
    if score >= THRESHOLD_POLICY["blocked_duplicate"]:
        return "blocked_duplicate"
    if score >= THRESHOLD_POLICY["revise_required"]:
        return "revise_required"
    if score >= THRESHOLD_POLICY["pass_with_watch"]:
        return "pass_with_watch"
    return "pass"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def candidate_text(row: sqlite3.Row) -> str:
    output = _json_object(row["output_json"] if "output_json" in row.keys() else None)
    parts: list[str] = []
    parts.extend(_question_texts(output))
    return "\n".join(part.strip() for part in parts if part and part.strip())


def audit_candidate_batch(
    conn: sqlite3.Connection,
    candidates: list[sqlite3.Row],
    embed_url: str,
    embed_model: str = DEFAULT_EMBED_MODEL,
    *,
    embedder: Callable[[list[str], str, str], list[list[float]]] = llama_embed,
) -> list[dict[str, Any]]:
    return _audit_rows(
        conn,
        candidates,
        embed_url,
        embed_model,
        id_kind="candidate",
        embedder=embedder,
    )


def audit_question_batch(
    conn: sqlite3.Connection,
    questions: list[sqlite3.Row],
    embed_url: str,
    embed_model: str = DEFAULT_EMBED_MODEL,
    *,
    embedder: Callable[[list[str], str, str], list[list[float]]] = llama_embed,
) -> list[dict[str, Any]]:
    return _audit_rows(
        conn,
        questions,
        embed_url,
        embed_model,
        id_kind="question",
        embedder=embedder,
    )


def _audit_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    embed_url: str,
    embed_model: str,
    *,
    id_kind: str,
    embedder: Callable[[list[str], str, str], list[list[float]]],
) -> list[dict[str, Any]]:
    texts = [candidate_text(row) for row in rows]
    missing_text_ids = [row["id"] for row, text in zip(rows, texts) if not text.strip()]
    if missing_text_ids:
        label = "candidate" if id_kind == "candidate" else "question"
        raise ValueError(f"{label} output text is required before similarity audit: {missing_text_ids}")
    candidate_vectors = embedder(texts, embed_url, embed_model) if texts else []
    if len(candidate_vectors) != len(rows):
        raise ValueError(
            f"embedding vector count mismatch: expected {len(rows)}, got {len(candidate_vectors)}"
        )
    corpus = _historical_corpus(conn)
    results: list[dict[str, Any]] = []
    for row, text, candidate_vector in zip(rows, texts, candidate_vectors):
        best_score = 0.0
        best_hit: sqlite3.Row | None = None
        for corpus_row in corpus:
            corpus_vector = load_vector(corpus_row["embedding_json"])
            if not corpus_vector:
                continue
            score = cosine_similarity(candidate_vector, corpus_vector)
            if score > best_score:
                best_score = score
                best_hit = corpus_row
        results.append(
            {
                "candidate_id": row["id"] if id_kind == "candidate" else None,
                "question_id": row["id"] if id_kind == "question" else None,
                "audit_result": classify_similarity(best_score),
                "top_score": best_score,
                "matched_source_kind": best_hit["kind"] if best_hit else "",
                "matched_source_id": best_hit["source_id"] if best_hit else None,
                "matched_chunk_id": best_hit["id"] if best_hit else None,
                "matched_question_id": None,
                "match_reason": classify_similarity(best_score),
                "snippet": (best_hit["text"][:240] if best_hit else ""),
                "candidate_text": text,
            }
        )
    return results


def _historical_corpus(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.id, c.source_id, s.kind, c.text, c.embedding_json
        FROM chunks c
        JOIN sources s ON s.id = c.source_id
        WHERE s.kind IN ('historical_exam', 'question_bank')
          AND c.embedding_json IS NOT NULL
        ORDER BY s.kind, c.id
        """
    ).fetchall()


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _question_texts(data: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for field in ["stem", "material", "analysis", "topic"]:
        if data.get(field):
            texts.append(str(data[field]))
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ["stem", "material", "analysis"]:
                if item.get(field):
                    texts.append(str(item[field]))
            options = item.get("options")
            if isinstance(options, list):
                texts.extend(str(option.get("text")) for option in options if isinstance(option, dict) and option.get("text"))
    return texts
