from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

import llamaindex_sqlite_vec_rag as rag


pytest.importorskip("sqlite_vec")


def test_sqlite_vec_rag_indexes_chunks_and_reports_source_hits(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "materials" / "stats.md"
    source.parent.mkdir()
    source.write_text("# stats\nsample variance uses n-1.\ncorrelation measures linear relation.", encoding="utf-8")

    nodes = [
        rag.RagNode(
            text="sample variance uses n-1 as denominator.",
            source_path=str(source.resolve()),
            source_name=source.name,
            node_id="node-1",
            chunk_index=1,
            locator="chunk:1",
            char_start=0,
            char_end=39,
            metadata={"file_path": str(source.resolve())},
        ),
        rag.RagNode(
            text="correlation measures linear relation strength.",
            source_path=str(source.resolve()),
            source_name=source.name,
            node_id="node-2",
            chunk_index=2,
            locator="chunk:2",
            char_start=40,
            char_end=84,
            metadata={"file_path": str(source.resolve())},
        ),
    ]

    monkeypatch.setattr(rag, "load_nodes_with_llamaindex", lambda *_args, **_kwargs: nodes)

    def fake_embed(texts, *_args, **_kwargs):
        vectors = []
        for text in texts:
            if "variance" in text or "n-1" in text:
                vectors.append([1.0, 0.0])
            elif "correlation" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.9, 0.1])
        return vectors

    monkeypatch.setattr(rag, "llama_embed", fake_embed)

    db = tmp_path / "rag.sqlite"
    indexed = rag.index_paths(
        db_path=str(db),
        input_paths=[source.parent],
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        chunk_size=128,
        chunk_overlap=16,
        reset=True,
    )

    assert indexed["ok"] is True
    assert indexed["sources"] == 1
    assert indexed["chunks"] == 2

    result = rag.query_index(
        db_path=str(db),
        query="sample variance n-1",
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        top_k=2,
        vector_k=5,
        fts_k=5,
        knowledge_points=["variance", "correlation"],
        semantic_threshold=0.8,
        weak_threshold=0.3,
        max_chars=160,
    )

    assert result["ok"] is True
    first = result["hits"][0]
    assert first["source_path"] == str(source.resolve())
    assert first["chunk_id"]
    assert first["node_id"] == "node-1"
    assert first["chunk_index"] == 1
    assert first["char_start"] == 0
    assert "sample variance" in first["hit_text"]
    assert "vector" in first["retrieval_modes"]
    assert "fts5" in first["retrieval_modes"]
    assert "variance" in first["lexical_terms"]
    assert first["knowledge_hit_ids"]
    assert first["knowledge_judgement"][0]["knowledge_point"] == "variance"
    assert first["knowledge_judgement"][0]["status"] == "matched"
    assert first["knowledge_judgement"][0]["lexical_match"] is True
    assert first["knowledge_judgement"][0]["knowledge_hit_id"] == first["knowledge_hit_ids"][0]

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        point_rows = conn.execute(
            "SELECT knowledge_point, normalized_text FROM rag_knowledge_points ORDER BY knowledge_point"
        ).fetchall()
        hit_rows = conn.execute(
            """
            SELECT knowledge_point, chunk_id, source_id, status, lexical_match, semantic_score,
                   matched_text, retrieval_modes_json, lexical_terms_json
            FROM rag_knowledge_hits
            ORDER BY knowledge_point
            """
        ).fetchall()
    finally:
        conn.close()

    assert {row["knowledge_point"] for row in point_rows} == {"correlation", "variance"}
    assert {row["normalized_text"] for row in point_rows} == {"correlation", "variance"}
    assert len(hit_rows) == 4
    variance_hit = next(row for row in hit_rows if row["knowledge_point"] == "variance")
    assert variance_hit["chunk_id"] == first["chunk_id"]
    assert variance_hit["source_id"]
    assert variance_hit["status"] == "matched"
    assert variance_hit["lexical_match"] == 1
    assert "sample variance" in variance_hit["matched_text"]
    assert "vector" in variance_hit["retrieval_modes_json"]
    assert "variance" in variance_hit["lexical_terms_json"]


def test_sqlite_vec_rag_fts_uses_knowledge_points_when_query_is_natural(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "materials" / "stats.md"
    source.parent.mkdir()
    source.write_text("样本方差使用 n-1 是为了修正估计偏差。相关系数用于衡量线性关系。", encoding="utf-8")

    nodes = [
        rag.RagNode(
            text="样本方差使用 n-1 是为了修正估计偏差。",
            source_path=str(source.resolve()),
            source_name=source.name,
            node_id="node-1",
            chunk_index=1,
            locator="chunk:1",
            char_start=0,
            char_end=24,
            metadata={"file_path": str(source.resolve())},
        ),
        rag.RagNode(
            text="相关系数用于衡量线性关系。",
            source_path=str(source.resolve()),
            source_name=source.name,
            node_id="node-2",
            chunk_index=2,
            locator="chunk:2",
            char_start=25,
            char_end=38,
            metadata={"file_path": str(source.resolve())},
        ),
    ]

    monkeypatch.setattr(rag, "load_nodes_with_llamaindex", lambda *_args, **_kwargs: nodes)

    def fake_embed(texts, *_args, **_kwargs):
        vectors = []
        for text in texts:
            if "相关" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([1.0, 0.0])
        return vectors

    monkeypatch.setattr(rag, "llama_embed", fake_embed)

    db = tmp_path / "rag.sqlite"
    rag.index_paths(
        db_path=str(db),
        input_paths=[source.parent],
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        chunk_size=128,
        chunk_overlap=16,
        reset=True,
    )

    result = rag.query_index(
        db_path=str(db),
        query="为什么分母这样设置",
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        top_k=2,
        vector_k=2,
        fts_k=5,
        knowledge_points=["样本方差", "n-1"],
        semantic_threshold=0.8,
        weak_threshold=0.3,
        max_chars=160,
    )

    first = result["hits"][0]
    assert first["chunk_id"]
    assert "fts5" in first["retrieval_modes"]
    assert "vector" in first["retrieval_modes"]
    assert "样本方差" in first["lexical_terms"]
    assert first["knowledge_hit_ids"]
    assert first["knowledge_judgement"][0]["status"] == "matched"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.knowledge_point, h.chunk_id, h.status, h.lexical_match, h.semantic_score
            FROM rag_knowledge_points p
            JOIN rag_knowledge_hits h ON h.knowledge_point_id = p.id
            ORDER BY p.knowledge_point
            """
        ).fetchall()
    finally:
        conn.close()

    assert {row["knowledge_point"] for row in rows} == {"n-1", "样本方差"}
    first_chunk_rows = [row for row in rows if row["chunk_id"] == first["chunk_id"]]
    assert {row["knowledge_point"] for row in first_chunk_rows} == {"n-1", "样本方差"}
    assert any(row["status"] == "matched" and row["lexical_match"] == 1 for row in first_chunk_rows)


def test_sqlite_vec_rag_query_fails_closed_on_empty_index(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"

    with pytest.raises(RuntimeError, match="index is empty or incomplete"):
        rag.query_index(
            db_path=str(db),
            query="样本方差",
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
            top_k=1,
            vector_k=1,
            fts_k=1,
            knowledge_points=["样本方差"],
            semantic_threshold=0.8,
            weak_threshold=0.3,
            max_chars=80,
        )
