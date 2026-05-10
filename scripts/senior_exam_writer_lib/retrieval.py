from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import sys
from typing import Any

from .common import Evidence
from .evidence_roles import item_role_for_source_kind, role_for_source_kind
from .llama_cpp_client import llama_embed

def tokenize_query(query: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", query)
    if not terms and query.strip():
        terms = [query.strip()]
    return terms[:12]

def fts_match_query(query: str) -> str:
    terms = tokenize_query(query)
    escaped = []
    for term in terms:
        term = term.replace('"', '""')
        escaped.append(f'"{term}"')
    return " OR ".join(escaped) if escaped else '""'

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

def keyword_substring_score(query: str, text: str, path: str, title: str) -> float:
    haystack = f"{title}\n{path}\n{text}".lower()
    score = 0.0
    for term in tokenize_query(query):
        score += haystack.count(term.lower()) * 0.6
    if len(query.strip()) >= 2 and query.strip().lower() in haystack:
        score += 1.2
    return score

def retrieve_evidence(
    conn: sqlite3.Connection,
    query: str,
    *,
    top_k: int,
    embed_url: str | None,
    embed_model: str,
    layers: set[str] | None = None,
) -> list[Evidence]:
    layers = layers or {"overview", "toc", "parent", "content"}
    route_paths: set[str] = set()
    fts_q = fts_match_query(query)

    route_rows: list[sqlite3.Row] = []
    try:
        route_rows = conn.execute(
            """
            SELECT c.*, s.kind, s.title AS source_title, s.path AS source_path, s.source_name, s.url, s.published_at,
                   bm25(chunks_fts) AS bm25_rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            JOIN sources s ON s.id = c.source_id
            WHERE chunks_fts MATCH ? AND c.layer IN ('overview', 'toc')
            ORDER BY bm25_rank
            LIMIT 20
            """,
            (fts_q,),
        ).fetchall()
    except sqlite3.OperationalError:
        route_rows = []
    for row in route_rows:
        if row["path"]:
            route_paths.add(row["path"])
        for line in (row["text"] or "").splitlines():
            if any(term in line for term in tokenize_query(query)):
                route_paths.add(line.strip())

    candidates: dict[str, dict[str, Any]] = {}
    try:
        rows = conn.execute(
            """
            SELECT c.*, s.kind, s.title AS source_title, s.path AS source_path, s.source_name, s.url, s.published_at,
                   bm25(chunks_fts) AS bm25_rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            JOIN sources s ON s.id = c.source_id
            WHERE chunks_fts MATCH ?
            ORDER BY bm25_rank
            LIMIT 80
            """,
            (fts_q,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for row in rows:
        if row["layer"] not in layers:
            continue
        bm25_score = 1.0 / (1.0 + max(0.0, float(row["bm25_rank"])))
        candidates[row["id"]] = {"row": row, "score": bm25_score * 2.0}

    rows = conn.execute(
        """
        SELECT c.*, s.kind, s.title AS source_title, s.path AS source_path, s.source_name, s.url, s.published_at
        FROM chunks c
        JOIN sources s ON s.id = c.source_id
        WHERE c.layer IN ('parent', 'content')
        """
    ).fetchall()
    query_vec = None
    if embed_url:
        try:
            query_vec = llama_embed([query], embed_url, embed_model)[0]
        except Exception as exc:
            print(f"[warn] embedding retrieval disabled: {exc}", file=sys.stderr)
    for row in rows:
        if row["layer"] not in layers:
            continue
        score = keyword_substring_score(query, row["text"], row["path"] or "", row["title"] or "")
        if route_paths and any(rp and (rp in (row["path"] or "") or (row["path"] or "") in rp) for rp in route_paths):
            score += 0.8
        if query_vec:
            vec = load_vector(row["embedding_json"])
            if vec:
                score += max(0.0, cosine(query_vec, vec)) * 2.5
        if score <= 0:
            continue
        current = candidates.get(row["id"])
        if current:
            current["score"] += score
        else:
            candidates[row["id"]] = {"row": row, "score": score}

    expanded: dict[str, dict[str, Any]] = {}
    for item in candidates.values():
        row = item["row"]
        score = float(item["score"])
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
                if not prev or prev["score"] < score + 0.35:
                    expanded[parent["id"]] = {"row": parent, "score": score + 0.35}
        prev = expanded.get(row["id"])
        if not prev or prev["score"] < score:
            expanded[row["id"]] = {"row": row, "score": score}

    ranked = sorted(expanded.values(), key=lambda x: x["score"], reverse=True)
    evidences: list[Evidence] = []
    seen_text: set[str] = set()
    for idx, item in enumerate(ranked, 1):
        row = item["row"]
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
                score=round(float(item["score"]), 4),
                source_title=row["source_title"] or "",
                source_path=row["source_path"] or "",
                source_kind=row["kind"],
                source_name=row["source_name"],
                source_url=row["url"],
                published_at=row["published_at"],
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
