from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .common import now_iso
from .dedup import normalized_point_set


def read_json_arg(value: str | None, label: str) -> Any:
    if value is None:
        return {}
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be JSON or a path to a JSON file") from exc


def create_or_update_task(
    conn: sqlite3.Connection,
    *,
    task_id: str | None,
    name: str,
    outline: Any,
    source_policy: Any,
    question_rules: Any,
    requirements: Any,
    coverage: Any,
    status: str,
) -> dict[str, Any]:
    existing = conn.execute("SELECT * FROM exam_tasks WHERE id = ?", (task_id,)).fetchone() if task_id else None
    now = now_iso()
    final_id = task_id or str(uuid.uuid4())
    created_at = existing["created_at"] if existing else now
    conn.execute(
        """
        INSERT INTO exam_tasks
        (id, name, outline_json, source_policy_json, question_rules_json,
         requirements_json, coverage_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          outline_json = excluded.outline_json,
          source_policy_json = excluded.source_policy_json,
          question_rules_json = excluded.question_rules_json,
          requirements_json = excluded.requirements_json,
          coverage_json = excluded.coverage_json,
          status = excluded.status,
          updated_at = excluded.updated_at
        """,
        (
            final_id,
            name,
            json.dumps(outline or {}, ensure_ascii=False),
            json.dumps(source_policy or {}, ensure_ascii=False),
            json.dumps(question_rules or {}, ensure_ascii=False),
            json.dumps(requirements or {}, ensure_ascii=False),
            json.dumps(coverage or {}, ensure_ascii=False),
            status,
            created_at,
            now,
        ),
    )
    conn.commit()
    return task_to_json(get_task(conn, final_id))


def get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM exam_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise ValueError(f"task not found: {task_id}")
    return row


def task_to_json(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "outline": json.loads(row["outline_json"] or "{}"),
        "source_policy": json.loads(row["source_policy_json"] or "{}"),
        "question_rules": json.loads(row["question_rules_json"] or "{}"),
        "requirements": json.loads(row["requirements_json"] or "{}"),
        "coverage": json.loads(row["coverage_json"] or "{}"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_tasks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.*,
               COUNT(q.id) AS question_runs,
               SUM(CASE WHEN q.status = 'ok' THEN 1 ELSE 0 END) AS ok_runs
        FROM exam_tasks t
        LEFT JOIN questions q ON q.task_id = t.id
        GROUP BY t.id
        ORDER BY t.updated_at DESC
        """
    ).fetchall()
    data = []
    for row in rows:
        item = task_to_json(row)
        item["question_runs"] = int(row["question_runs"] or 0)
        item["ok_runs"] = int(row["ok_runs"] or 0)
        data.append(item)
    return data


def load_task_context(conn: sqlite3.Connection, task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    return task_to_json(get_task(conn, task_id))


def record_review(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    reviewer: str | None,
    decision: str,
    notes: str | None,
    patch: Any,
) -> dict[str, Any]:
    qrow = conn.execute("SELECT id FROM questions WHERE id = ?", (question_id,)).fetchone()
    if not qrow:
        raise ValueError(f"question not found: {question_id}")
    review_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO question_reviews
        (id, question_id, reviewer, decision, notes, patch_json, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id,
            question_id,
            reviewer,
            decision,
            notes,
            json.dumps(patch or {}, ensure_ascii=False),
            now_iso(),
        ),
    )
    conn.commit()
    return {
        "id": review_id,
        "question_id": question_id,
        "reviewer": reviewer,
        "decision": decision,
        "notes": notes,
        "patch": patch or {},
    }


def prior_question_context(
    conn: sqlite3.Connection,
    *,
    task_id: str | None,
    limit: int = 50,
) -> dict[str, Any]:
    if not task_id:
        return {"items": [], "knowledge_points": []}
    rows = conn.execute(
        """
        SELECT q.id, q.topic, q.question_type, q.output_json, q.status, q.created_at,
               (
                 SELECT r.decision
                 FROM question_reviews r
                 WHERE r.question_id = q.id
                 ORDER BY r.reviewed_at DESC
                 LIMIT 1
               ) AS review_decision
        FROM questions q
        WHERE q.task_id = ?
          AND q.status = 'ok'
        ORDER BY q.created_at DESC
        LIMIT ?
        """,
        (task_id, limit),
    ).fetchall()
    items: list[dict[str, Any]] = []
    all_points: list[str] = []
    for row in rows:
        if row["review_decision"] == "rejected":
            continue
        try:
            output = json.loads(row["output_json"] or "{}")
        except json.JSONDecodeError:
            continue
        for item in output.get("items") or []:
            if not isinstance(item, dict):
                continue
            points = item.get("knowledge_points") or []
            if isinstance(points, str):
                points = [points]
            points = [str(point).strip() for point in points if str(point).strip()]
            if not points:
                alignment = item.get("style_profile", {}).get("syllabus_alignment") if isinstance(item.get("style_profile"), dict) else None
                points = [str(alignment or item.get("stem") or row["topic"])[:120]]
            all_points.extend(points)
            items.append(
                {
                    "question_id": row["id"],
                    "item_id": item.get("id"),
                    "topic": row["topic"],
                    "question_type": row["question_type"],
                    "review_decision": row["review_decision"] or "unreviewed",
                    "knowledge_points": points,
                    "stem": item.get("stem", "")[:220],
                }
            )
    return {"items": items, "knowledge_points": sorted(set(all_points))}


def duplicate_points_against_prior(output: dict[str, Any], prior_context: dict[str, Any]) -> list[str]:
    prior = normalized_point_set([str(point) for point in prior_context.get("knowledge_points") or []])
    issues: list[str] = []
    for idx, item in enumerate(output.get("items") or [], 1):
        if not isinstance(item, dict):
            continue
        points = item.get("knowledge_points") or []
        if isinstance(points, str):
            points = [points]
        repeated = normalized_point_set([str(point) for point in points]) & prior
        if repeated:
            issues.append(f"item {idx}: knowledge_points overlap with prior task output")
    return issues


def task_status(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    task = task_to_json(get_task(conn, task_id))
    source_counts = {
        row["kind"]: int(row["n"])
        for row in conn.execute("SELECT kind, COUNT(*) AS n FROM sources GROUP BY kind").fetchall()
    }
    run_counts = {
        row["status"]: int(row["n"])
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM questions WHERE task_id = ? GROUP BY status",
            (task_id,),
        ).fetchall()
    }
    review_counts = {
        row["decision"]: int(row["n"])
        for row in conn.execute(
            """
            SELECT r.decision, COUNT(*) AS n
            FROM question_reviews r
            JOIN questions q ON q.id = r.question_id
            WHERE q.task_id = ?
            GROUP BY r.decision
            """,
            (task_id,),
        ).fetchall()
    }
    prior = prior_question_context(conn, task_id=task_id)
    return {
        "task": task,
        "source_counts": source_counts,
        "question_run_counts": run_counts,
        "review_counts": review_counts,
        "covered_knowledge_points": prior["knowledge_points"],
        "covered_item_count": len(prior["items"]),
    }
