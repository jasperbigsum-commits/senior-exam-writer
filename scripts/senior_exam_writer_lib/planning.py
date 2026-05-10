from __future__ import annotations

from typing import Any

from .common import now_iso, stable_id


def _normalize_points(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _outline_points_for_target(outline: dict[str, Any], target: str) -> list[str]:
    if not target:
        return []
    _, _, leaf = target.partition("/")
    modules = outline.get("modules")
    if isinstance(modules, list):
        for module in modules:
            if not isinstance(module, dict):
                continue
            names = {
                str(module.get("name") or "").strip(),
                str(module.get("title") or "").strip(),
            }
            if target.split("/", 1)[0] not in names:
                continue
            points = _normalize_points(module.get("objectives"))
            if leaf and leaf in points:
                return [leaf]
            if points:
                return points
    objectives = _normalize_points(outline.get("objectives"))
    if leaf and leaf in objectives:
        return [leaf]
    return [leaf] if leaf else objectives


def _objective_for_target(target: str, knowledge_points: list[str]) -> str:
    module, _, leaf = target.partition("/")
    focus = leaf or (knowledge_points[0] if knowledge_points else "")
    if module and focus:
        return f"{module} objective {focus}"
    return target or focus


def build_planning_units(task_context: dict[str, Any]) -> list[dict[str, Any]]:
    coverage = task_context.get("coverage") or {}
    outline = task_context.get("outline") or {}
    task_id = str(task_context.get("id") or "")
    units: list[dict[str, Any]] = []
    for row in coverage.get("distribution") or []:
        if not isinstance(row, dict):
            continue
        target = str(row.get("target") or "").strip()
        question_type = str(row.get("question_type") or "").strip()
        difficulty = str(row.get("difficulty") or "").strip()
        count = int(row.get("count") or 0)
        knowledge_points = _outline_points_for_target(outline, target)
        objective = _objective_for_target(target, knowledge_points)
        for offset in range(count):
            timestamp = now_iso()
            units.append(
                {
                    "id": stable_id(task_id, target, question_type, difficulty, str(offset)),
                    "task_id": task_id,
                    "coverage_target": target,
                    "objective": objective,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "knowledge_points": knowledge_points,
                    "knowledge_status": "planned",
                    "evidence_status": "pending",
                    "writer_round": 0,
                    "review_status": "pending",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
    return units
