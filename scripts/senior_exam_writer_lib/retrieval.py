from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from .common import Evidence
from .evidence_roles import item_role_for_source_kind, role_for_source_kind
from .llama_cpp_client import llama_embed


@dataclass(frozen=True)
class RetrievalCandidate:
    row: sqlite3.Row
    score: float

def add_candidate(
    candidates: dict[str, RetrievalCandidate],
    row: sqlite3.Row,
    score: float,
) -> None:
    current = candidates.get(row["id"])
    if current:
        candidates[row["id"]] = RetrievalCandidate(row=row, score=current.score + score)
    else:
        candidates[row["id"]] = RetrievalCandidate(row=row, score=score)

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def load_vector(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        return [float(x) for x in json.loads(raw)]
    except Exception:
        return None

def load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def retrieve_evidence(
    conn: sqlite3.Connection,
    query: str,
    *,
    top_k: int,
    embed_url: str | None,
    embed_model: str,
    layers: set[str] | None = None,
) -> list[Evidence]:
    if not embed_url:
        raise ValueError("vector retrieval requires embed_url")
    layers = layers or {"overview", "toc", "parent", "content"}
    candidates: dict[str, RetrievalCandidate] = {}
    rows = conn.execute(
        """
        SELECT c.*, s.kind, s.title AS source_title, s.path AS source_path, s.source_name, s.url, s.published_at
        FROM chunks c
        JOIN sources s ON s.id = c.source_id
        WHERE c.layer IN ('overview', 'toc', 'parent', 'content')
        """
    ).fetchall()
    query_vec = None
    if embed_url:
        query_vec = llama_embed([query], embed_url, embed_model)[0]
    semantic_rows: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        if row["layer"] not in layers:
            continue
        if query_vec:
            vec = load_vector(row["embedding_json"])
            if vec:
                similarity = cosine(query_vec, vec)
                if similarity > 0:
                    semantic_rows.append((similarity, row))
    semantic_limit = max(80, top_k * 12)
    for rank, (similarity, row) in enumerate(sorted(semantic_rows, key=lambda item: item[0], reverse=True)[:semantic_limit], 1):
        add_candidate(candidates, row, max(0.0, similarity))

    expanded: dict[str, RetrievalCandidate] = {}
    for item in candidates.values():
        row = item.row
        score = float(item.score)
        if row["layer"] == "content" and row["parent_id"]:
            parent = conn.execute(
                """
                SELECT c.*, s.kind, s.title AS source_title, s.path AS source_path, s.source_name, s.url, s.published_at
                FROM chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE c.id = ?
                """,
                (row["parent_id"],),
            ).fetchone()
            if parent:
                prev = expanded.get(parent["id"])
                if not prev or prev.score < score + 0.35:
                    expanded[parent["id"]] = RetrievalCandidate(row=parent, score=score + 0.35)
        prev = expanded.get(row["id"])
        if not prev or prev.score < score:
            expanded[row["id"]] = RetrievalCandidate(row=row, score=score)

    ranked = sorted(expanded.values(), key=lambda x: x.score, reverse=True)
    evidences: list[Evidence] = []
    seen_text: set[str] = set()
    for idx, item in enumerate(ranked, 1):
        row = item.row
        metadata = load_metadata(row["metadata_json"])
        digest = hashlib.sha1((row["text"] or "")[:500].encode("utf-8", errors="ignore")).hexdigest()
        if digest in seen_text:
            continue
        seen_text.add(digest)
        evidences.append(
            Evidence(
                id=f"E{len(evidences) + 1}",
                chunk_id=row["id"],
                source_id=row["source_id"],
                layer=row["layer"],
                path=row["path"] or "",
                title=row["title"] or "",
                locator=row["locator"] or "",
                text=row["text"] or "",
                score=round(float(item.score), 4),
                source_title=row["source_title"] or "",
                source_path=row["source_path"] or "",
                source_kind=row["kind"],
                source_name=row["source_name"] or metadata.get("source_name"),
                source_url=row["url"] or metadata.get("source_url"),
                published_at=row["published_at"] or metadata.get("published_at"),
            )
        )
        if len(evidences) >= top_k:
            break
    return evidences

def evidence_to_json(evidence: list[Evidence], max_chars: int = 1200) -> list[dict[str, Any]]:
    data = []
    for ev in evidence:
        data.append(
            {
                "id": ev.id,
                "chunk_id": ev.chunk_id,
                "layer": ev.layer,
                "score": ev.score,
                "source_kind": ev.source_kind,
                "role": role_for_source_kind(ev.source_kind),
                "item_role": item_role_for_source_kind(ev.source_kind),
                "citation": ev.citation(),
                "path": ev.path,
                "locator": ev.locator,
                "text": ev.text[:max_chars],
            }
        )
    return data

def has_locator(ev: Evidence) -> bool:
    return bool(ev.source_title or ev.source_path) and bool(ev.locator or ev.path)

def gate_evidence(evidence: list[Evidence], min_evidence: int, strict_current: bool = False) -> tuple[bool, dict[str, Any]]:
    final = [ev for ev in evidence if ev.layer in {"parent", "content"}]
    with_locators = [ev for ev in final if has_locator(ev)]
    issues = []
    if len(final) < min_evidence:
        issues.append(f"need at least {min_evidence} content/parent evidence chunks, got {len(final)}")
    if len(with_locators) < min_evidence:
        issues.append(f"need at least {min_evidence} cited evidence chunks, got {len(with_locators)}")
    if strict_current:
        dated = [ev for ev in with_locators if ev.published_at or ev.source_url]
        if len(dated) < min_evidence:
            issues.append("strict current-affairs mode requires dated URL/file-located sources")
    return not issues, {"ok": not issues, "issues": issues, "usable_evidence": len(with_locators)}
