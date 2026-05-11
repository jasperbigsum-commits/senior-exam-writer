from __future__ import annotations

from pathlib import Path

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
    assert first["knowledge_judgement"][0]["knowledge_point"] == "variance"
    assert first["knowledge_judgement"][0]["status"] == "matched"
    assert first["knowledge_judgement"][0]["lexical_match"] is True


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
    assert first["knowledge_judgement"][0]["status"] == "matched"


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
