#!/usr/bin/env python3
"""LlamaIndex ingestion into local sqlite-vec plus FTS5 hybrid retrieval."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

from senior_exam_writer_lib.common import configure_stdio_utf8, now_iso, stable_id
from senior_exam_writer_lib.ingest import collect_files
from senior_exam_writer_lib.llama_cpp_client import llama_embed
from senior_exam_writer_lib.retrieval import cosine, load_vector


@dataclass(frozen=True)
class RagNode:
    text: str
    source_path: str
    source_name: str
    node_id: str
    chunk_index: int
    locator: str
    char_start: int | None
    char_end: int | None
    metadata: dict[str, Any]


def connect_rag_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception as exc:
        raise RuntimeError(
            "sqlite-vec is mandatory for this local RAG path; run `uv sync --extra rag` "
            "from the skill directory and retry"
        ) from exc
    return conn


def init_rag_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rag_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_sources (
          id TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          name TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_chunks (
          rowid INTEGER PRIMARY KEY,
          id TEXT NOT NULL UNIQUE,
          source_id TEXT NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
          source_path TEXT NOT NULL,
          source_name TEXT NOT NULL,
          node_id TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          locator TEXT,
          char_start INTEGER,
          char_end INTEGER,
          text TEXT NOT NULL,
          embedding_json TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_knowledge_points (
          id TEXT PRIMARY KEY,
          knowledge_point TEXT NOT NULL UNIQUE,
          normalized_text TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rag_knowledge_hits (
          id TEXT PRIMARY KEY,
          knowledge_point_id TEXT NOT NULL REFERENCES rag_knowledge_points(id) ON DELETE CASCADE,
          knowledge_point TEXT NOT NULL,
          query TEXT NOT NULL,
          chunk_id TEXT NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
          source_id TEXT NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
          status TEXT NOT NULL,
          lexical_match INTEGER NOT NULL,
          semantic_score REAL NOT NULL,
          matched_text TEXT NOT NULL,
          retrieval_modes_json TEXT NOT NULL DEFAULT '[]',
          lexical_terms_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(query, knowledge_point, chunk_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
          chunk_id UNINDEXED,
          source_id UNINDEXED,
          source_path UNINDEXED,
          locator UNINDEXED,
          text,
          tokenize='trigram'
        );

        CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_id ON rag_chunks(id);
        CREATE INDEX IF NOT EXISTS idx_rag_knowledge_points_text ON rag_knowledge_points(normalized_text);
        CREATE INDEX IF NOT EXISTS idx_rag_knowledge_hits_point ON rag_knowledge_hits(knowledge_point);
        CREATE INDEX IF NOT EXISTS idx_rag_knowledge_hits_chunk ON rag_knowledge_hits(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_rag_knowledge_hits_status ON rag_knowledge_hits(status);
        """
    )
    conn.commit()


def ensure_vec_table(conn: sqlite3.Connection, dimension: int) -> None:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")
    row = conn.execute("SELECT value FROM rag_meta WHERE key = 'vector_dimension'").fetchone()
    if row and int(row["value"]) != dimension:
        raise RuntimeError(
            f"sqlite-vec dimension mismatch: db={row['value']} requested={dimension}; use --reset or a new db"
        )
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(embedding float[{int(dimension)}])")
    conn.execute(
        "INSERT INTO rag_meta(key, value) VALUES('vector_dimension', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(dimension),),
    )
    conn.commit()


def reset_rag_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS rag_vec;
        DROP TABLE IF EXISTS rag_knowledge_hits;
        DROP TABLE IF EXISTS rag_knowledge_points;
        DROP TABLE IF EXISTS rag_chunks_fts;
        DROP TABLE IF EXISTS rag_chunks;
        DROP TABLE IF EXISTS rag_sources;
        DROP TABLE IF EXISTS rag_meta;
        """
    )
    conn.commit()
    init_rag_schema(conn)


def load_nodes_with_llamaindex(paths: list[Path], *, chunk_size: int, chunk_overlap: int) -> list[RagNode]:
    try:
        from llama_index.core import SimpleDirectoryReader  # type: ignore
        from llama_index.core.node_parser import SentenceSplitter  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "LlamaIndex is mandatory for file loading and chunk splitting; run `uv sync --extra rag` "
            "from the skill directory and retry"
        ) from exc

    files = _collect_supported_files(paths)
    if not files:
        return []
    documents = SimpleDirectoryReader(input_files=[str(path) for path in files]).load_data()
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    nodes = splitter.get_nodes_from_documents(documents)
    records: list[RagNode] = []
    per_source_index: dict[str, int] = {}
    for node in nodes:
        metadata = dict(getattr(node, "metadata", {}) or {})
        text = str(node.get_content(metadata_mode="none") or "").lstrip("\ufeff").strip()
        if not text:
            continue
        source_path = str(metadata.get("file_path") or metadata.get("path") or metadata.get("filename") or "")
        if source_path:
            source_path = str(Path(source_path).expanduser().resolve())
        else:
            source_path = str(files[0].resolve())
        source_name = str(metadata.get("file_name") or metadata.get("filename") or Path(source_path).name)
        per_source_index[source_path] = per_source_index.get(source_path, 0) + 1
        start = getattr(node, "start_char_idx", None)
        end = getattr(node, "end_char_idx", None)
        page = metadata.get("page_label") or metadata.get("page") or metadata.get("loc")
        locator = f"page:{page}" if page else f"chunk:{per_source_index[source_path]}"
        records.append(
            RagNode(
                text=text,
                source_path=source_path,
                source_name=source_name,
                node_id=str(getattr(node, "node_id", "") or stable_id(source_path, text[:200])),
                chunk_index=per_source_index[source_path],
                locator=locator,
                char_start=int(start) if isinstance(start, int) else None,
                char_end=int(end) if isinstance(end, int) else None,
                metadata=metadata,
            )
        )
    return records


def _collect_supported_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        for file_path in collect_files(path):
            key = str(file_path.resolve()).lower()
            if key not in seen:
                files.append(file_path)
                seen.add(key)
    return sorted(files, key=lambda item: str(item).lower())


def index_paths(
    *,
    db_path: str,
    input_paths: list[Path],
    embed_url: str,
    embed_model: str,
    chunk_size: int,
    chunk_overlap: int,
    reset: bool = False,
    batch_size: int = 8,
) -> dict[str, Any]:
    conn = connect_rag_db(db_path)
    try:
        if reset:
            reset_rag_db(conn)
        else:
            init_rag_schema(conn)
        nodes = load_nodes_with_llamaindex(input_paths, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not nodes:
            return {"ok": False, "error": "no nodes loaded", "db": db_path, "nodes": 0}
        vectors = _embed_texts([node.text for node in nodes], embed_url, embed_model, batch_size=batch_size)
        dimension = _validate_vectors(vectors)
        ensure_vec_table(conn, dimension)

        source_ids = sorted({stable_id(node.source_path) for node in nodes})
        for source_id in source_ids:
            _delete_source(conn, source_id)

        source_seen: set[str] = set()
        indexed_chunks = 0
        for node, vector in zip(nodes, vectors):
            source_id = stable_id(node.source_path)
            if source_id not in source_seen:
                conn.execute(
                    """
                    INSERT INTO rag_sources(id, path, name, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        node.source_path,
                        node.source_name,
                        json.dumps({"loader": "llamaindex"}, ensure_ascii=False),
                        now_iso(),
                    ),
                )
                source_seen.add(source_id)
            chunk_id = stable_id(node.source_path, node.node_id, str(node.chunk_index), node.text[:200])
            cursor = conn.execute(
                """
                INSERT INTO rag_chunks
                (
                  id, source_id, source_path, source_name, node_id, chunk_index,
                  locator, char_start, char_end, text, embedding_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    source_id,
                    node.source_path,
                    node.source_name,
                    node.node_id,
                    node.chunk_index,
                    node.locator,
                    node.char_start,
                    node.char_end,
                    node.text,
                    json.dumps(vector, ensure_ascii=False),
                    json.dumps(node.metadata, ensure_ascii=False),
                    now_iso(),
                ),
            )
            rowid = int(cursor.lastrowid)
            _insert_vec(conn, rowid, vector)
            conn.execute(
                """
                INSERT INTO rag_chunks_fts(rowid, chunk_id, source_id, source_path, locator, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rowid, chunk_id, source_id, node.source_path, node.locator, node.text),
            )
            indexed_chunks += 1
        conn.commit()
        return {
            "ok": True,
            "db": db_path,
            "backend": "llamaindex+sqlite-vec+fts5",
            "sources": len(source_seen),
            "chunks": indexed_chunks,
            "embedding": {"model": embed_model, "dimension": dimension, "url": embed_url},
        }
    finally:
        conn.close()


def query_index(
    *,
    db_path: str,
    query: str,
    embed_url: str,
    embed_model: str,
    top_k: int,
    vector_k: int,
    fts_k: int,
    knowledge_points: list[str],
    semantic_threshold: float,
    weak_threshold: float,
    max_chars: int,
) -> dict[str, Any]:
    conn = connect_rag_db(db_path)
    try:
        init_rag_schema(conn)
        _ensure_query_ready(conn)
        query_vec = llama_embed([query], embed_url, embed_model)[0]
        point_texts = knowledge_points or [query]
        point_vectors = llama_embed(point_texts, embed_url, embed_model) if point_texts else []
        vector_rows = _vector_search(conn, query_vec, vector_k)
        fts_rows = _fts_search(conn, query, fts_k, knowledge_points=knowledge_points)
        combined = _combine_rows(vector_rows, fts_rows)
        hits = []
        persisted_hit_count = 0
        for rank, candidate in enumerate(combined[:top_k], 1):
            row = _chunk_by_rowid(conn, candidate["rowid"])
            if not row:
                continue
            chunk_vec = load_vector(row["embedding_json"]) or []
            snippet = candidate.get("snippet") or _snippet(row["text"], [query, *point_texts], max_chars=max_chars)
            judgements = _knowledge_judgements(
                point_texts,
                point_vectors,
                row["text"],
                chunk_vec,
                semantic_threshold=semantic_threshold,
                weak_threshold=weak_threshold,
                max_chars=max_chars,
            )
            knowledge_hit_ids = _persist_knowledge_hits(
                conn,
                query=query,
                chunk=row,
                judgements=judgements,
                retrieval_modes=candidate["modes"],
                lexical_terms=candidate.get("lexical_terms", []),
                vector_distance=candidate.get("vector_distance"),
                fts_rank=candidate.get("fts_rank"),
            )
            persisted_hit_count += len(knowledge_hit_ids)
            hits.append(
                {
                    "rank": rank,
                    "score": round(float(candidate["score"]), 6),
                    "retrieval_modes": candidate["modes"],
                    "lexical_terms": candidate.get("lexical_terms", []),
                    "vector_distance": candidate.get("vector_distance"),
                    "fts_rank": candidate.get("fts_rank"),
                    "source_path": row["source_path"],
                    "source_name": row["source_name"],
                    "source_id": row["source_id"],
                    "chunk_id": row["id"],
                    "node_id": row["node_id"],
                    "chunk_index": row["chunk_index"],
                    "locator": row["locator"],
                    "char_start": row["char_start"],
                    "char_end": row["char_end"],
                    "snippet": snippet,
                    "hit_text": row["text"][:max_chars],
                    "knowledge_judgement": judgements,
                    "knowledge_hit_ids": knowledge_hit_ids,
                }
            )
        conn.commit()
        return {
            "ok": True,
            "query": query,
            "backend": "llamaindex+sqlite-vec+fts5",
            "top_k": top_k,
            "persisted_knowledge_hits": persisted_hit_count,
            "hits": hits,
        }
    finally:
        conn.close()


def _embed_texts(texts: list[str], embed_url: str, embed_model: str, *, batch_size: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(llama_embed(texts[start : start + batch_size], embed_url, embed_model))
    return vectors


def _validate_vectors(vectors: list[list[float]]) -> int:
    if not vectors or not vectors[0]:
        raise RuntimeError("embedding endpoint returned no vectors; fix the local llama.cpp embedding runtime first")
    dimension = len(vectors[0])
    for idx, vector in enumerate(vectors, 1):
        if not vector:
            raise RuntimeError(f"embedding endpoint returned an empty vector at batch item {idx}")
        if len(vector) != dimension:
            raise RuntimeError(
                f"embedding endpoint returned inconsistent vector dimensions: first={dimension}, item_{idx}={len(vector)}"
            )
    return dimension


def _ensure_query_ready(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM rag_meta WHERE key = 'vector_dimension'").fetchone()
    chunk_count = int(conn.execute("SELECT COUNT(*) AS count FROM rag_chunks").fetchone()["count"])
    if not row or chunk_count == 0:
        raise RuntimeError(
            "sqlite-vec RAG index is empty or incomplete; run `uv run --extra rag python "
            "scripts/llamaindex_sqlite_vec_rag.py index ...` before query"
        )


def _delete_source(conn: sqlite3.Connection, source_id: str) -> None:
    rows = conn.execute("SELECT rowid, id FROM rag_chunks WHERE source_id = ?", (source_id,)).fetchall()
    rowids = [int(row["rowid"]) for row in rows]
    chunk_ids = [str(row["id"]) for row in rows]
    for chunk_id in chunk_ids:
        conn.execute("DELETE FROM rag_knowledge_hits WHERE chunk_id = ?", (chunk_id,))
    for rowid in rowids:
        conn.execute("DELETE FROM rag_chunks_fts WHERE rowid = ?", (rowid,))
        conn.execute("DELETE FROM rag_vec WHERE rowid = ?", (rowid,))
    conn.execute("DELETE FROM rag_chunks WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM rag_sources WHERE id = ?", (source_id,))


def _insert_vec(conn: sqlite3.Connection, rowid: int, vector: list[float]) -> None:
    import sqlite_vec  # type: ignore

    conn.execute(
        "INSERT INTO rag_vec(rowid, embedding) VALUES (?, ?)",
        (rowid, sqlite_vec.serialize_float32(vector)),
    )


def _vector_search(conn: sqlite3.Connection, vector: list[float], limit: int) -> list[dict[str, Any]]:
    import sqlite_vec  # type: ignore

    rows = conn.execute(
        """
        SELECT rowid, distance
        FROM rag_vec
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """,
        (sqlite_vec.serialize_float32(vector), int(limit)),
    ).fetchall()
    return [{"rowid": int(row["rowid"]), "distance": float(row["distance"])} for row in rows]


def _fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    *,
    knowledge_points: list[str] | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    terms = _lexical_terms(query, knowledge_points or [])
    found: dict[int, dict[str, Any]] = {}
    for term_order, term in enumerate(terms):
        if len(term) < 3:
            continue
        expr = _quote_fts_phrase(term)
        try:
            rows = conn.execute(
                """
                SELECT rowid, bm25(rag_chunks_fts) AS rank_score,
                       snippet(rag_chunks_fts, 4, '[', ']', '...', 32) AS snippet_text
                FROM rag_chunks_fts
                WHERE rag_chunks_fts MATCH ?
                ORDER BY bm25(rag_chunks_fts)
                LIMIT ?
                """,
                (expr, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        _merge_fts_rows(found, rows, term=term, term_order=term_order, mode="fts5")
        if len(found) >= limit:
            break

    # FTS5 trigram ignores very short or punctuation-heavy terms such as "n-1".
    # LIKE is only a lexical locator fallback; vector retrieval still provides semantic ranking.
    if len(found) < limit:
        for term_order, term in enumerate(terms):
            if len(term) < 2:
                continue
            like = f"%{term}%"
            rows = conn.execute(
                """
                SELECT rowid, 0.0 AS rank_score, text AS snippet_text
                FROM rag_chunks_fts
                WHERE text LIKE ?
                LIMIT ?
                """,
                (like, int(limit)),
            ).fetchall()
            _merge_fts_rows(found, rows, term=term, term_order=term_order, mode="like")
            if len(found) >= limit:
                break

    return sorted(
        found.values(),
        key=lambda item: (int(item.get("term_order", 9999)), float(item.get("rank_score", 0.0)), int(item["rowid"])),
    )[:limit]


def _merge_fts_rows(
    found: dict[int, dict[str, Any]],
    rows: list[sqlite3.Row],
    *,
    term: str,
    term_order: int,
    mode: str,
) -> None:
    for row in rows:
        rowid = int(row["rowid"])
        rank_score = float(row["rank_score"])
        snippet = str(row["snippet_text"] or "")
        current = found.get(rowid)
        if current is None:
            current = {
                "rowid": rowid,
                "rank_score": rank_score,
                "snippet": snippet,
                "lexical_terms": [],
                "term_order": term_order,
                "lexical_modes": [],
            }
            found[rowid] = current
        if term not in current["lexical_terms"]:
            current["lexical_terms"].append(term)
        if mode not in current["lexical_modes"]:
            current["lexical_modes"].append(mode)
        if term_order < int(current.get("term_order", term_order)):
            current["term_order"] = term_order
        if not current.get("snippet") or mode == "fts5":
            current["snippet"] = snippet
        current["rank_score"] = min(float(current.get("rank_score", rank_score)), rank_score)


def _quote_fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./+-]*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def _lexical_terms(query: str, knowledge_points: list[str]) -> list[str]:
    candidates: list[str] = []
    for text in [*knowledge_points, query]:
        clean = " ".join(str(text or "").split())
        if not clean:
            continue
        candidates.append(clean)
        ascii_terms = _ASCII_TERM_RE.findall(clean)
        candidates.extend(term for term in ascii_terms if len(term) >= 2)
        candidates.extend(f"{left} {right}" for left, right in zip(ascii_terms, ascii_terms[1:]))
        for run in _CJK_RUN_RE.findall(clean):
            if len(run) <= 8:
                candidates.append(run)
            for size in (6, 5, 4, 3):
                if len(run) >= size:
                    candidates.extend(run[start : start + size] for start in range(0, len(run) - size + 1))

    seen: set[str] = set()
    terms: list[str] = []
    for term in candidates:
        normalized = term.strip()
        if len(normalized) < 2 or normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
        if len(terms) >= 48:
            break
    return terms


def _combine_rows(vector_rows: list[dict[str, Any]], fts_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: dict[int, dict[str, Any]] = {}
    rrf_k = 60.0
    for rank, item in enumerate(vector_rows, 1):
        rowid = int(item["rowid"])
        score = 1.0 / (rrf_k + rank)
        combined.setdefault(rowid, {"rowid": rowid, "score": 0.0, "modes": []})
        combined[rowid]["score"] += score
        combined[rowid]["modes"].append("vector")
        combined[rowid]["vector_distance"] = round(float(item["distance"]), 6)
    for rank, item in enumerate(fts_rows, 1):
        rowid = int(item["rowid"])
        score = 1.0 / (rrf_k + rank)
        combined.setdefault(rowid, {"rowid": rowid, "score": 0.0, "modes": []})
        combined[rowid]["score"] += score
        combined[rowid]["modes"].append("fts5")
        combined[rowid]["fts_rank"] = round(float(item["rank_score"]), 6)
        combined[rowid]["snippet"] = item.get("snippet")
        combined[rowid]["lexical_terms"] = item.get("lexical_terms", [])
    return sorted(combined.values(), key=lambda item: item["score"], reverse=True)


def _chunk_by_rowid(conn: sqlite3.Connection, rowid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM rag_chunks WHERE rowid = ?", (rowid,)).fetchone()


def _knowledge_judgements(
    points: list[str],
    point_vectors: list[list[float]],
    text: str,
    chunk_vec: list[float],
    *,
    semantic_threshold: float,
    weak_threshold: float,
    max_chars: int,
) -> list[dict[str, Any]]:
    results = []
    for idx, point in enumerate(points):
        point_vec = point_vectors[idx] if idx < len(point_vectors) else []
        similarity = cosine(point_vec, chunk_vec) if point_vec and chunk_vec else 0.0
        lexical = bool(point and point in text)
        if lexical or similarity >= semantic_threshold:
            status = "matched"
        elif similarity >= weak_threshold:
            status = "weak"
        else:
            status = "missing"
        results.append(
            {
                "knowledge_point": point,
                "status": status,
                "lexical_match": lexical,
                "semantic_score": round(float(similarity), 4),
                "matched_text": _snippet(text, [point], max_chars=max_chars) if lexical else "",
            }
        )
    return results


def _persist_knowledge_hits(
    conn: sqlite3.Connection,
    *,
    query: str,
    chunk: sqlite3.Row,
    judgements: list[dict[str, Any]],
    retrieval_modes: list[str],
    lexical_terms: list[str],
    vector_distance: float | None,
    fts_rank: float | None,
) -> list[str]:
    now = now_iso()
    hit_ids: list[str] = []
    for judgement in judgements:
        point = str(judgement.get("knowledge_point") or "").strip()
        if not point:
            continue
        normalized = _normalize_knowledge_point(point)
        point_id = stable_id("rag_knowledge_point", normalized)
        hit_id = stable_id("rag_knowledge_hit", query, normalized, str(chunk["id"]))
        conn.execute(
            """
            INSERT INTO rag_knowledge_points(id, knowledge_point, normalized_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(knowledge_point) DO UPDATE SET
              normalized_text = excluded.normalized_text,
              updated_at = excluded.updated_at
            """,
            (point_id, point, normalized, now, now),
        )
        conn.execute(
            """
            INSERT INTO rag_knowledge_hits
            (
              id, knowledge_point_id, knowledge_point, query, chunk_id, source_id,
              status, lexical_match, semantic_score, matched_text,
              retrieval_modes_json, lexical_terms_json, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(query, knowledge_point, chunk_id) DO UPDATE SET
              knowledge_point_id = excluded.knowledge_point_id,
              source_id = excluded.source_id,
              status = excluded.status,
              lexical_match = excluded.lexical_match,
              semantic_score = excluded.semantic_score,
              matched_text = excluded.matched_text,
              retrieval_modes_json = excluded.retrieval_modes_json,
              lexical_terms_json = excluded.lexical_terms_json,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                hit_id,
                point_id,
                point,
                query,
                str(chunk["id"]),
                str(chunk["source_id"]),
                str(judgement.get("status") or "missing"),
                1 if judgement.get("lexical_match") else 0,
                float(judgement.get("semantic_score") or 0.0),
                str(judgement.get("matched_text") or ""),
                json.dumps(retrieval_modes, ensure_ascii=False),
                json.dumps(lexical_terms, ensure_ascii=False),
                json.dumps(
                    {
                        "vector_distance": vector_distance,
                        "fts_rank": fts_rank,
                        "source_path": chunk["source_path"],
                        "source_name": chunk["source_name"],
                        "locator": chunk["locator"],
                    },
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        judgement["knowledge_hit_id"] = hit_id
        hit_ids.append(hit_id)
    return hit_ids


def _normalize_knowledge_point(point: str) -> str:
    return " ".join(str(point or "").casefold().split())


def _snippet(text: str, needles: list[str], *, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    positions = [clean.find(needle) for needle in needles if needle]
    positions = [pos for pos in positions if pos >= 0]
    if not positions:
        return clean[:max_chars]
    start = max(0, min(positions) - max_chars // 3)
    end = min(len(clean), start + max_chars)
    return clean[start:end]


def cmd_index(args: argparse.Namespace) -> int:
    payload = index_paths(
        db_path=args.db,
        input_paths=[Path(path) for path in args.input],
        embed_url=args.embed_url,
        embed_model=args.embed_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        reset=args.reset,
        batch_size=args.batch_size,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def cmd_query(args: argparse.Namespace) -> int:
    points = list(args.knowledge_point or [])
    if args.knowledge_points_json:
        loaded = json.loads(Path(args.knowledge_points_json).read_text(encoding="utf-8-sig"))
        if isinstance(loaded, list):
            points.extend(str(item) for item in loaded)
    payload = query_index(
        db_path=args.db,
        query=args.query,
        embed_url=args.embed_url,
        embed_model=args.embed_model,
        top_k=args.top_k,
        vector_k=args.vector_k,
        fts_k=args.fts_k,
        knowledge_points=points,
        semantic_threshold=args.semantic_threshold,
        weak_threshold=args.weak_threshold,
        max_chars=args.max_chars,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index files with LlamaIndex into sqlite-vec and query with FTS5+vector hybrid retrieval.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("index", help="load files through LlamaIndex, split nodes, embed locally, and store in sqlite-vec")
    p.add_argument("--db", required=True)
    p.add_argument("--input", action="append", required=True)
    p.add_argument("--embed-url", default="http://127.0.0.1:8081")
    p.add_argument("--embed-model", default="local-embedding")
    p.add_argument("--chunk-size", type=int, default=512)
    p.add_argument("--chunk-overlap", type=int, default=80)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--reset", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("query", help="hybrid query and return source file, chunk, split locator, hit text, and knowledge judgement")
    p.add_argument("--db", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--embed-url", default="http://127.0.0.1:8081")
    p.add_argument("--embed-model", default="local-embedding")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--vector-k", type=int, default=20)
    p.add_argument("--fts-k", type=int, default=20)
    p.add_argument("--knowledge-point", action="append")
    p.add_argument("--knowledge-points-json")
    p.add_argument("--semantic-threshold", type=float, default=0.55)
    p.add_argument("--weak-threshold", type=float, default=0.35)
    p.add_argument("--max-chars", type=int, default=500)
    p.set_defaults(func=cmd_query)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error_type": exc.__class__.__name__, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
