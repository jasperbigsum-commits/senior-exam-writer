from __future__ import annotations

from typing import Any

from .retrieval import retrieve_evidence


def classify_support(point_to_evidence: dict[str, list[str]]) -> str:
    if not point_to_evidence:
        return "missing"
    counts = [len(ids) for ids in point_to_evidence.values()]
    if counts and all(count > 0 for count in counts):
        return "strong"
    if any(count > 0 for count in counts):
        return "partial"
    return "missing"


def build_evidence_points(
    conn: Any,
    unit: dict[str, Any],
    embed_url: str,
    embed_model: str,
) -> dict[str, Any]:
    bundle = _collect_evidence_bundle(conn, unit, embed_url, embed_model)
    return {
        "planning_unit_id": unit["id"],
        "mapping": bundle["mapping"],
        "support_status": classify_support(bundle["mapping"]),
    }


def collect_evidence_records(
    conn: Any,
    unit: dict[str, Any],
    embed_url: str,
    embed_model: str,
) -> dict[str, list[dict[str, str | None]]]:
    return _collect_evidence_bundle(conn, unit, embed_url, embed_model)["records"]


def _collect_evidence_bundle(
    conn: Any,
    unit: dict[str, Any],
    embed_url: str,
    embed_model: str,
) -> dict[str, dict[str, list[Any]]]:
    mapping: dict[str, list[str]] = {}
    records: dict[str, list[dict[str, str | None]]] = {}
    for point in unit.get("knowledge_points") or []:
        point_text = str(point).strip()
        if not point_text:
            continue
        evidence = retrieve_evidence(
            conn,
            point_text,
            top_k=6,
            embed_url=embed_url,
            embed_model=embed_model,
        )
        point_records = [
            {
                "evidence_id": item.id,
                "chunk_id": item.chunk_id,
                "source_id": item.source_id,
            }
            for item in evidence
            if item.layer in {"parent", "content"} and item.id
        ]
        records[point_text] = point_records
        mapping[point_text] = [str(item["evidence_id"]) for item in point_records if item.get("evidence_id")]
    return {"mapping": mapping, "records": records}
