from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .common import SUPPORTED_SUFFIXES, now_iso, stable_id
from .dedup import (
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_SEMANTIC_DEDUP_THRESHOLD,
    backfill_missing_fingerprints,
    find_duplicate_chunk,
    record_chunk_fingerprint,
    record_duplicate_chunk,
    summarize_duplicates,
)
from .llama_cpp_client import llama_embed
from .parsing import approx_tokens, chunk_text, load_document, sections_from_parts
from .source_metadata import metadata_from_structured_text

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

def insert_unique_chunk(
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
    dedup: bool = True,
    dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD,
    semantic_dedup_threshold: float = DEFAULT_SEMANTIC_DEDUP_THRESHOLD,
) -> tuple[bool, str | None]:
    if dedup:
        duplicate = find_duplicate_chunk(
            conn,
            text=text,
            layer=layer,
            threshold=dedup_threshold,
            embedding=embedding,
            semantic_threshold=semantic_dedup_threshold,
        )
        if duplicate:
            record_duplicate_chunk(
                conn,
                source_id=source_id,
                candidate_id=chunk_id,
                duplicate=duplicate,
                layer=layer,
                path=path,
                title=title,
                locator=locator,
                text=text,
            )
            return False, duplicate.duplicate_of_chunk_id
    insert_chunk(
        conn,
        chunk_id=chunk_id,
        source_id=source_id,
        parent_id=parent_id,
        layer=layer,
        path=path,
        title=title,
        locator=locator,
        text=text,
        metadata=metadata,
        embedding=embedding,
    )
    record_chunk_fingerprint(conn, chunk_id=chunk_id, source_id=source_id, layer=layer, text=text)
    return True, None

def batch_embed(texts: list[str], embed: bool, embed_url: str, embed_model: str, batch_size: int = 8) -> list[list[float] | None]:
    if not embed:
        return [None] * len(texts)
    vectors: list[list[float] | None] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(llama_embed(batch, embed_url, embed_model))
    return vectors

def delete_source_tree(conn: sqlite3.Connection, source_id: str) -> None:
    chunk_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
    ]
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

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
    dedup: bool = True,
    dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD,
    semantic_dedup_threshold: float = DEFAULT_SEMANTIC_DEDUP_THRESHOLD,
) -> dict[str, Any]:
    doc_title = title or path.stem
    parts = load_document(path)
    sections, toc_titles = sections_from_parts(parts, doc_title)
    source_id = stable_id(str(path.resolve()), doc_title, kind, version or "")
    if dedup:
        backfill_missing_fingerprints(conn)

    delete_source_tree(conn, source_id)
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

    section_metadata = [metadata_from_structured_text(section.text) if kind == "current_affairs" else {} for section in sections]
    overview_text = "\n".join(section.text[:500] for section in sections[:3])[:1800]
    overview_id = stable_id(source_id, "overview")
    toc_text = "\n".join(toc_titles[:500]) or "\n".join(section.path for section in sections[:200])
    toc_id = stable_id(source_id, "toc")
    overview_vec, toc_vec = batch_embed([overview_text, toc_text], embed, embed_url, embed_model)
    overview_inserted, _ = insert_unique_chunk(
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
        dedup=dedup,
        dedup_threshold=dedup_threshold,
        semantic_dedup_threshold=semantic_dedup_threshold,
    )
    toc_inserted, _ = insert_unique_chunk(
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
        dedup=dedup,
        dedup_threshold=dedup_threshold,
        semantic_dedup_threshold=semantic_dedup_threshold,
    )

    parent_count = 0
    child_count = 0
    for sidx, section in enumerate(sections, 1):
        metadata = section_metadata[sidx - 1] if sidx - 1 < len(section_metadata) else {}
        parent_id = stable_id(source_id, "parent", str(sidx), section.path, section.text[:200])
        parent_vec = batch_embed([f"{section.path}\n{section.text[:1800]}"], embed, embed_url, embed_model)[0]
        parent_inserted, _duplicate_parent = insert_unique_chunk(
            conn,
            chunk_id=parent_id,
            source_id=source_id,
            parent_id=None,
            layer="parent",
            path=section.path,
            title=section.title,
            locator=section.locator,
            text=section.text,
            metadata={"level": section.level, **metadata},
            embedding=parent_vec,
            dedup=dedup,
            dedup_threshold=dedup_threshold,
            semantic_dedup_threshold=semantic_dedup_threshold,
        )
        if not parent_inserted:
            continue
        parent_count += 1

        child_texts = chunk_text(section.text, max_chars=max_chars)
        child_vectors = batch_embed([f"{section.path}\n{txt}" for txt in child_texts], embed, embed_url, embed_model)
        for cidx, (child, child_vec) in enumerate(zip(child_texts, child_vectors), 1):
            child_id = stable_id(source_id, "content", str(sidx), str(cidx), section.path, child[:200])
            child_inserted, _duplicate_child = insert_unique_chunk(
                conn,
                chunk_id=child_id,
                source_id=source_id,
                parent_id=parent_id,
                layer="content",
                path=section.path,
                title=section.title,
                locator=f"{section.locator}#chunk-{cidx}",
                text=child,
                metadata={"level": section.level, "chunk_index": cidx, **metadata},
                embedding=child_vec,
                dedup=dedup,
                dedup_threshold=dedup_threshold,
                semantic_dedup_threshold=semantic_dedup_threshold,
            )
            if child_inserted:
                child_count += 1
    conn.commit()
    return {
        "source_id": source_id,
        "title": doc_title,
        "overview": int(overview_inserted),
        "toc": int(toc_inserted),
        "parents": parent_count,
        "children": child_count,
        "dedup": summarize_duplicates(conn, source_id),
    }
