from __future__ import annotations

import sqlite3

from senior_exam_writer_lib.retrieval import retrieve_evidence
from senior_exam_writer_lib.store import init_db


def _insert_source(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO sources
        (id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("source-1", "book", "教材", "book.txt", None, None, None, None, "{}", "2026-05-11T00:00:00+08:00"),
    )


def _insert_chunk(
    conn: sqlite3.Connection,
    chunk_id: str,
    text: str,
    vector: str,
    *,
    title: str,
    path: str,
) -> None:
    conn.execute(
        """
        INSERT INTO chunks
        (id, source_id, parent_id, layer, path, title, locator, text, token_count, embedding_json, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            "source-1",
            None,
            "parent",
            path,
            title,
            "p.1",
            text,
            10,
            vector,
            "{}",
            "2026-05-11T00:00:00+08:00",
        ),
    )

def test_retrieve_evidence_defaults_to_vector_ranking(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "retrieval.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        _insert_source(conn)
        _insert_chunk(conn, "lexical", "苹果 香蕉 水果", "[1.0, 0.0]", title="水果", path="第一章")
        _insert_chunk(conn, "semantic", "偏导数 梯度 极值", "[0.0, 1.0]", title="高等数学", path="第二章")
        conn.commit()

        monkeypatch.setattr("senior_exam_writer_lib.retrieval.llama_embed", lambda *_args, **_kwargs: [[0.0, 1.0]])

        evidence = retrieve_evidence(
            conn,
            "苹果",
            top_k=2,
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    finally:
        conn.close()

    assert [item.chunk_id for item in evidence] == ["semantic"]
    assert evidence[0].source_kind == "book"


def test_retrieve_evidence_vector_mode_does_not_promote_lexical_decoy(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "retrieval.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        _insert_source(conn)
        _insert_chunk(conn, "lexical-decoy", "苹果 苹果 苹果 但这是无关水果知识", "[0.1, 0.0]", title="水果", path="第一章")
        _insert_chunk(conn, "semantic", "导数 梯度 极值 与经济统计优化", "[0.0, 1.0]", title="高等数学", path="第二章")
        conn.commit()

        monkeypatch.setattr("senior_exam_writer_lib.retrieval.llama_embed", lambda *_args, **_kwargs: [[0.0, 1.0]])

        evidence = retrieve_evidence(
            conn,
            "苹果",
            top_k=1,
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    finally:
        conn.close()

    assert [item.chunk_id for item in evidence] == ["semantic"]


def test_retrieve_evidence_vector_mode_requires_embedding_endpoint(tmp_path) -> None:
    db_path = tmp_path / "retrieval.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        _insert_source(conn)
        _insert_chunk(conn, "keyword", "苹果 香蕉 水果", "[0.1, 0.0]", title="水果", path="第一章")
        conn.commit()

        try:
            retrieve_evidence(
                conn,
                "苹果",
                top_k=1,
                embed_url=None,
                embed_model="local-embedding",
            )
        except ValueError as exc:
            assert "vector retrieval requires embed_url" in str(exc)
        else:
            raise AssertionError("vector retrieval should require embed_url")
    finally:
        conn.close()
