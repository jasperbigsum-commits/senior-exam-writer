from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .common import SUPPORTED_SUFFIXES, now_iso, stable_id
from .llama_cpp_client import llama_embed
from .parsing import approx_tokens, chunk_text, load_document, sections_from_parts

def collect_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    files = []
    for path in sorted(input_path.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return files

def insert_chunk(
    conn: sqlite3.Connection,
    *,
    chunk_id: str,
    source_id: str,
    parent_id: str | None,
    layer: str,
    path: str,
    title: str,
    locator: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO chunks
        (id, source_id, parent_id, layer, path, title, locator, text, token_count, embedding_json, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            source_id,
            parent_id,
            layer,
            path,
            title,
            locator,
            text,
            approx_tokens(text),
            json.dumps(embedding, ensure_ascii=False) if embedding is not None else None,
            json.dumps(metadata or {}, ensure_ascii=False),
            now_iso(),
        ),
    )
    conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
    conn.execute(
        "INSERT INTO chunks_fts(chunk_id, title, path, text) VALUES (?, ?, ?, ?)",
        (chunk_id, title, path, text),
    )

def batch_embed(texts: list[str], embed: bool, embed_url: str, embed_model: str, batch_size: int = 8) -> list[list[float] | None]:
    if not embed:
        return [None] * len(texts)
    vectors: list[list[float] | None] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(llama_embed(batch, embed_url, embed_model))
    return vectors

def ingest_file(
    conn: sqlite3.Connection,
    path: Path,
    *,
    kind: str,
    title: str | None,
    source_name: str | None,
    url: str | None,
    published_at: str | None,
    version: str | None,
    embed: bool,
    embed_url: str,
    embed_model: str,
    max_chars: int,
) -> dict[str, Any]:
    doc_title = title or path.stem
    parts = load_document(path)
    sections, toc_titles = sections_from_parts(parts, doc_title)
    source_id = stable_id(str(path.resolve()), doc_title, kind, version or "")

    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.execute(
        """
        INSERT INTO sources(id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            kind,
            doc_title,
            str(path.resolve()),
            source_name,
            url,
            published_at,
            version,
            json.dumps({"suffix": path.suffix.lower()}, ensure_ascii=False),
            now_iso(),
        ),
    )

    overview_text = "\n".join(section.text[:500] for section in sections[:3])[:1800]
    overview_id = stable_id(source_id, "overview")
    toc_text = "\n".join(toc_titles[:500]) or "\n".join(section.path for section in sections[:200])
    toc_id = stable_id(source_id, "toc")
    overview_vec, toc_vec = batch_embed([overview_text, toc_text], embed, embed_url, embed_model)
    insert_chunk(
        conn,
        chunk_id=overview_id,
        source_id=source_id,
        parent_id=None,
        layer="overview",
        path=doc_title,
        title=f"{doc_title} overview",
        locator="overview",
        text=overview_text or doc_title,
        embedding=overview_vec,
    )
    insert_chunk(
        conn,
        chunk_id=toc_id,
        source_id=source_id,
        parent_id=None,
        layer="toc",
        path=doc_title,
        title=f"{doc_title} TOC",
        locator="toc",
        text=toc_text or doc_title,
        embedding=toc_vec,
    )

    parent_count = 0
    child_count = 0
    for sidx, section in enumerate(sections, 1):
        parent_id = stable_id(source_id, "parent", str(sidx), section.path, section.text[:200])
        parent_vec = batch_embed([f"{section.path}\n{section.text[:1800]}"], embed, embed_url, embed_model)[0]
        insert_chunk(
            conn,
            chunk_id=parent_id,
            source_id=source_id,
            parent_id=None,
            layer="parent",
            path=section.path,
            title=section.title,
            locator=section.locator,
            text=section.text,
            metadata={"level": section.level},
            embedding=parent_vec,
        )
        parent_count += 1

        child_texts = chunk_text(section.text, max_chars=max_chars)
        child_vectors = batch_embed([f"{section.path}\n{txt}" for txt in child_texts], embed, embed_url, embed_model)
        for cidx, (child, child_vec) in enumerate(zip(child_texts, child_vectors), 1):
            child_id = stable_id(source_id, "content", str(sidx), str(cidx), section.path, child[:200])
            insert_chunk(
                conn,
                chunk_id=child_id,
                source_id=source_id,
                parent_id=parent_id,
                layer="content",
                path=section.path,
                title=section.title,
                locator=f"{section.locator}#chunk-{cidx}",
                text=child,
                metadata={"level": section.level, "chunk_index": cidx},
                embedding=child_vec,
            )
            child_count += 1
    conn.commit()
    return {"source_id": source_id, "title": doc_title, "parents": parent_count, "children": child_count}

