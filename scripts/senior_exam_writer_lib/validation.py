from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .common import SOURCE_KINDS
from .dedup import normalized_point_set
from .evidence_roles import (
    ITEM_EVIDENCE_ROLE_ORDER,
    ITEM_EVIDENCE_ROLE_KEYS,
    SPEC_EVIDENCE_KINDS,
    item_role_for_source_kind,
    is_answer_evidence_kind,
)
from .runtime import ensure_local_base_url
from .source_metadata import current_affairs_metadata_issues

QUESTION_TYPES = {"single_choice", "multiple_choice", "material_analysis", "short_answer"}
DIFFICULTIES = {"easy", "medium", "hard"}
CANDIDATE_REVIEW_DECISIONS = {
    "approved_candidate",
    "revise_candidate",
    "replan_required",
    "evidence_gap",
    "rejected_candidate",
}
CANDIDATE_REASON_CODES = {
    "writer_quality_issue",
    "duplicate_risk_high",
    "outline_misalignment",
    "coverage_misalignment",
    "evidence_weak",
    "evidence_missing",
    "needs_replanning",
    "accepted",
}
BLOCKING_SIMILARITY_RESULTS = {"blocked_duplicate", "revise_required"}


class ValidationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("validation failed: " + "; ".join(issues))


def require_no_issues(issues: list[str]) -> None:
    if issues:
        raise ValidationError(issues)


def validate_local_endpoint(url: str, label: str) -> None:
    try:
        ensure_local_base_url(url)
    except ValueError as exc:
        raise ValidationError([f"{label} must use a local loopback URL: {url}"]) from exc


def as_dict(value: Any, label: str, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        issues.append(f"{label} must be a non-empty JSON object")
        return {}
    return value


def list_value(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def citation_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def append_unknown_citation_issues(
    *,
    issues: list[str],
    prefix: str,
    label: str,
    citations: Any,
    evidence_by_id: dict[str, Any],
) -> list[str]:
    if not isinstance(citations, list) or not citations:
        issues.append(f"{prefix}: {label} citations must be a non-empty list")
        return []
    normalized = citation_list(citations)
    unknown = [citation for citation in normalized if citation not in evidence_by_id]
    if unknown:
        issues.append(f"{prefix}: {label} contains unknown citations {unknown}")
    return normalized


def validate_task_definition(
    *,
    name: str,
    outline: Any,
    source_policy: Any,
    question_rules: Any,
    requirements: Any,
    coverage: Any,
    status: str,
) -> None:
    issues: list[str] = []
    if not str(name or "").strip():
        issues.append("task name is required")
    if status not in {"draft", "active", "paused", "completed"}:
        issues.append("task status must be draft, active, paused, or completed")

    outline_obj = as_dict(outline, "outline", issues)
    if outline_obj and not any(outline_obj.get(key) for key in ["exam_name", "modules", "objectives", "topics"]):
        issues.append("outline must include exam_name, modules, objectives, or topics")

    source_policy_obj = as_dict(source_policy, "source_policy", issues)
    if source_policy_obj:
        for key in ["required_core_kinds", "required_spec_kinds", "allowed_background_kinds", "any_core_kinds"]:
            bad = [kind for kind in list_value(source_policy_obj, key) if kind not in SOURCE_KINDS]
            if bad:
                issues.append(f"source_policy.{key} contains unsupported source kinds: {bad}")
        if not (
            list_value(source_policy_obj, "required_core_kinds")
            or list_value(source_policy_obj, "any_core_kinds")
            or list_value(source_policy_obj, "required_spec_kinds")
        ):
            issues.append("source_policy must declare required_core_kinds, any_core_kinds, or required_spec_kinds")
        if "current_affairs" in list_value(source_policy_obj, "allowed_background_kinds") and source_policy_obj.get(
            "current_affairs_requires_url_and_date"
        ) is not True:
            issues.append("source_policy.current_affairs_requires_url_and_date must be true when current_affairs is allowed")
        if source_policy_obj.get("question_bank_usage") not in {None, "style_only_no_copying"}:
            issues.append("source_policy.question_bank_usage must be style_only_no_copying when provided")

    question_rules_obj = as_dict(question_rules, "question_rules", issues)
    if question_rules_obj:
        qtypes = list_value(question_rules_obj, "question_types")
        if not qtypes:
            issues.append("question_rules.question_types must be a non-empty list")
        unsupported = [qtype for qtype in qtypes if qtype not in QUESTION_TYPES]
        if unsupported:
            issues.append(f"question_rules.question_types contains unsupported values: {unsupported}")
        if question_rules_obj.get("require_citations") is not True:
            issues.append("question_rules.require_citations must be true")
        if question_rules_obj.get("avoid_duplicate_knowledge_points") is not True:
            issues.append("question_rules.avoid_duplicate_knowledge_points must be true")

    requirements_obj = as_dict(requirements, "requirements", issues)
    if requirements_obj and requirements_obj.get("review_required") is not True:
        issues.append("requirements.review_required must be true")

    coverage_obj = as_dict(coverage, "coverage", issues)
    if coverage_obj:
        total_items = coverage_obj.get("total_items")
        distribution = list_value(coverage_obj, "distribution")
        if not isinstance(total_items, int) or total_items <= 0:
            issues.append("coverage.total_items must be a positive integer")
        if not distribution:
            issues.append("coverage.distribution must be a non-empty list")
        counted = 0
        for idx, row in enumerate(distribution, 1):
            if not isinstance(row, dict):
                issues.append(f"coverage.distribution[{idx}] must be an object")
                continue
            if not row.get("target"):
                issues.append(f"coverage.distribution[{idx}].target is required")
            if row.get("question_type") not in QUESTION_TYPES:
                issues.append(f"coverage.distribution[{idx}].question_type is invalid")
            if row.get("difficulty") not in DIFFICULTIES:
                issues.append(f"coverage.distribution[{idx}].difficulty is invalid")
            if not isinstance(row.get("count"), int) or row.get("count") <= 0:
                issues.append(f"coverage.distribution[{idx}].count must be a positive integer")
            else:
                counted += int(row["count"])
        if isinstance(total_items, int) and counted != total_items:
            issues.append("coverage.total_items must equal the sum of distribution counts")
        if coverage_obj.get("avoid_repeating_knowledge_points") is not True:
            issues.append("coverage.avoid_repeating_knowledge_points must be true")
    require_no_issues(issues)


def validate_ingest_request(
    *,
    input_path: Path,
    kind: str,
    source_name: str | None,
    url: str | None,
    published_at: str | None,
    allow_duplicate_chunks: bool,
) -> None:
    issues: list[str] = []
    if allow_duplicate_chunks:
        issues.append("duplicate chunk insertion is disabled by policy; remove --allow-duplicate-chunks")
    if kind not in SOURCE_KINDS:
        issues.append(f"unsupported source kind: {kind}")
    if kind == "current_affairs":
        issues.extend(
            current_affairs_metadata_issues(
                input_path=input_path,
                source_name=source_name,
                url=url,
                published_at=published_at,
            )
        )
    require_no_issues(issues)


def source_chunk_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["kind"]: int(row["n"])
        for row in conn.execute(
            """
            SELECT s.kind, COUNT(c.id) AS n
            FROM sources s
            JOIN chunks c ON c.source_id = s.id
            GROUP BY s.kind
            """
        ).fetchall()
    }


def validate_generation_request(
    *,
    conn: sqlite3.Connection,
    task_context: dict[str, Any] | None,
    question_type: str,
    count: int,
    difficulty: str,
    llm_verify: bool,
) -> None:
    issues: list[str] = []
    if not task_context:
        issues.append("generate requires --task-id; ad-hoc generation is disabled by policy")
        require_no_issues(issues)
    assert task_context is not None
    if task_context.get("status") not in {"active", "draft"}:
        issues.append("task status must be active or draft before generation")

    try:
        validate_task_definition(
            name=task_context.get("name", ""),
            outline=task_context.get("outline"),
            source_policy=task_context.get("source_policy"),
            question_rules=task_context.get("question_rules"),
            requirements=task_context.get("requirements"),
            coverage=task_context.get("coverage"),
            status=task_context.get("status", ""),
        )
    except ValidationError as exc:
        issues.extend(f"task definition: {issue}" for issue in exc.issues)

    question_rules = task_context.get("question_rules") or {}
    allowed_qtypes = list_value(question_rules, "question_types")
    if question_type not in allowed_qtypes:
        issues.append(f"question_type {question_type} is not allowed by task question_rules")
    if not isinstance(count, int) or count <= 0:
        issues.append("count must be a positive integer")
    if difficulty not in DIFFICULTIES:
        issues.append("difficulty is invalid")
    if not llm_verify:
        issues.append("LLM verification is mandatory; use --llm-verify")

    counts = source_chunk_counts(conn)
    missing_fingerprints = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM chunks c
        LEFT JOIN chunk_fingerprints fp ON fp.chunk_id = c.id
        WHERE fp.chunk_id IS NULL
        """
    ).fetchone()["n"]
    if int(missing_fingerprints or 0) > 0:
        issues.append("all chunks must have fingerprints before generation; run audit-duplicates --backfill")
    exact_duplicate_groups = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM (
          SELECT layer, text_hash
          FROM chunk_fingerprints
          GROUP BY layer, text_hash
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()["n"]
    if int(exact_duplicate_groups or 0) > 0:
        issues.append("knowledge base contains duplicate chunk fingerprints; clean duplicates before generation")
    policy = task_context.get("source_policy") or {}
    for kind in list_value(policy, "required_core_kinds") + list_value(policy, "required_spec_kinds"):
        if counts.get(kind, 0) <= 0:
            issues.append(f"required source kind has no indexed chunks: {kind}")
    any_core = list_value(policy, "any_core_kinds")
    if any_core and not any(counts.get(kind, 0) > 0 for kind in any_core):
        issues.append(f"at least one any_core_kinds source must have indexed chunks: {any_core}")
    require_no_issues(issues)


def validate_evidence_contract(
    *,
    evidence: list[Any],
    task_context: dict[str, Any] | None,
    strict_current: bool,
) -> None:
    issues: list[str] = []
    final = [ev for ev in evidence if ev.layer in {"parent", "content"}]
    answer_support = [ev for ev in final if is_answer_evidence_kind(ev.source_kind)]
    policy = (task_context or {}).get("source_policy") or {}
    allow_pure_current = policy.get("allow_pure_current_affairs") is True
    if not answer_support and not allow_pure_current:
        issues.append("generation requires parent/content answer evidence from book, handout, notes, or qa")
    if all(ev.source_kind == "question_bank" for ev in final) and final:
        issues.append("question_bank evidence cannot be the only retrieved final evidence")
    if all(ev.source_kind in SPEC_EVIDENCE_KINDS for ev in final) and final:
        issues.append("exam specification evidence cannot be the only answer evidence")
    if strict_current or any(ev.source_kind == "current_affairs" for ev in evidence):
        for ev in evidence:
            if ev.source_kind != "current_affairs":
                continue
            if not (ev.published_at and (ev.source_url or ev.source_path) and (ev.source_name or ev.source_title)):
                issues.append(f"current_affairs evidence {ev.id} lacks source/date/url-or-file metadata")
    require_no_issues(issues)


def validate_output_contract(
    *,
    output: dict[str, Any],
    evidence: list[Any],
    task_context: dict[str, Any] | None,
    question_type: str,
    count: int,
    difficulty: str,
) -> dict[str, Any]:
    issues: list[str] = []
    if output.get("status") == "refused":
        return {"ok": True, "mode": "policy", "issues": [], "refused": True}
    if output.get("question_type") != question_type:
        issues.append("output.question_type must match requested question_type")
    items = output.get("items")
    if not isinstance(items, list):
        issues.append("output.items must be a list")
        items = []
    elif len(items) != count:
        issues.append(f"output must contain exactly {count} items")

    evidence_by_id = {ev.id: ev for ev in evidence}
    coverage = (task_context or {}).get("coverage") or {}
    allowed_targets = [str(row.get("target")) for row in list_value(coverage, "distribution") if isinstance(row, dict)]
    seen_coverage: set[str] = set()
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        prefix = f"item {idx}"
        if item.get("difficulty") != difficulty:
            issues.append(f"{prefix}: difficulty must match requested difficulty")
        if "evidence_roles" not in item:
            issues.append(f"{prefix}: evidence_roles is required")
        if question_type in {"single_choice", "multiple_choice"}:
            options = item.get("options")
            if not isinstance(options, list) or len(options) < 2:
                issues.append(f"{prefix}: choice questions require at least two options")
                option_labels: list[str] = []
            else:
                option_labels = []
                seen_labels: set[str] = set()
                for opt_idx, option in enumerate(options, 1):
                    if not isinstance(option, dict):
                        issues.append(f"{prefix} option {opt_idx}: must be an object")
                        continue
                    label = str(option.get("label") or "")
                    option_labels.append(label)
                    if not label:
                        issues.append(f"{prefix} option {opt_idx}: label is required")
                    if label in seen_labels:
                        issues.append(f"{prefix}: duplicate option label {label}")
                    seen_labels.add(label)
                    if not str(option.get("text") or "").strip():
                        issues.append(f"{prefix} option {label or opt_idx}: text is required")
                    append_unknown_citation_issues(
                        issues=issues,
                        prefix=f"{prefix} option {label or opt_idx}",
                        label="option",
                        citations=option.get("citations"),
                        evidence_by_id=evidence_by_id,
                    )
            answer = item.get("answer")
            if question_type == "single_choice":
                if not isinstance(answer, str) or answer not in option_labels:
                    issues.append(f"{prefix}: single_choice answer must be one option label")
            if question_type == "multiple_choice":
                answer_labels = answer if isinstance(answer, list) else [part.strip() for part in str(answer or "").split(",")]
                if len([label for label in answer_labels if label]) < 2:
                    issues.append(f"{prefix}: multiple_choice answer must contain at least two labels")
                bad = [label for label in answer_labels if label and label not in option_labels]
                if bad:
                    issues.append(f"{prefix}: multiple_choice answer labels not in options: {bad}")
            option_audit = item.get("option_audit")
            if not isinstance(option_audit, list) or len(option_audit) != len(option_labels):
                issues.append(f"{prefix}: option_audit must audit every option")
            else:
                audited = {str(row.get("label") or "") for row in option_audit if isinstance(row, dict)}
                if set(option_labels) - audited:
                    issues.append(f"{prefix}: option_audit is missing labels {sorted(set(option_labels) - audited)}")
                for row in option_audit:
                    if not isinstance(row, dict):
                        continue
                    label = str(row.get("label") or "")
                    verdict = row.get("verdict")
                    if verdict not in {"correct", "incorrect"}:
                        issues.append(f"{prefix} option_audit {label}: verdict must be correct or incorrect")
                    if not str(row.get("reason") or "").strip():
                        issues.append(f"{prefix} option_audit {label}: reason is required")
                    append_unknown_citation_issues(
                        issues=issues,
                        prefix=f"{prefix} option_audit {label}",
                        label="option_audit",
                        citations=row.get("citations"),
                        evidence_by_id=evidence_by_id,
                    )
        if question_type == "short_answer":
            scoring_points = item.get("scoring_points")
            if not isinstance(scoring_points, list) or not scoring_points:
                issues.append(f"{prefix}: short_answer requires scoring_points")
            else:
                for point_idx, point in enumerate(scoring_points, 1):
                    if not isinstance(point, dict):
                        issues.append(f"{prefix} scoring_point {point_idx}: must be an object")
                        continue
                    if not str(point.get("point") or "").strip():
                        issues.append(f"{prefix} scoring_point {point_idx}: point is required")
                    append_unknown_citation_issues(
                        issues=issues,
                        prefix=f"{prefix} scoring_point {point_idx}",
                        label="scoring_point",
                        citations=point.get("citations"),
                        evidence_by_id=evidence_by_id,
                    )
        if question_type == "material_analysis" and not str(item.get("material") or "").strip():
            issues.append(f"{prefix}: material_analysis requires material")
        coverage_target = str(item.get("coverage_target") or "")
        if allowed_targets and not any(target and (target == coverage_target or target in coverage_target) for target in allowed_targets):
            issues.append(f"{prefix}: coverage_target is not in task coverage distribution")
        if coverage_target:
            if coverage_target in seen_coverage:
                issues.append(f"{prefix}: repeats coverage_target within the same batch")
            seen_coverage.add(coverage_target)
        citations = append_unknown_citation_issues(
            issues=issues,
            prefix=prefix,
            label="item",
            citations=item.get("citations"),
            evidence_by_id=evidence_by_id,
        )
        assertions = item.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            issues.append(f"{prefix}: assertions must be a non-empty list")
        else:
            for assertion_idx, assertion in enumerate(assertions, 1):
                if not isinstance(assertion, dict):
                    issues.append(f"{prefix} assertion {assertion_idx}: must be an object")
                    continue
                if not str(assertion.get("claim") or "").strip():
                    issues.append(f"{prefix} assertion {assertion_idx}: claim is required")
                append_unknown_citation_issues(
                    issues=issues,
                    prefix=f"{prefix} assertion {assertion_idx}",
                    label="assertion",
                    citations=assertion.get("citations"),
                    evidence_by_id=evidence_by_id,
                )
        cited_kinds = {evidence_by_id[c].source_kind for c in citations if c in evidence_by_id}
        if "question_bank" in cited_kinds:
            issues.append(f"{prefix}: question_bank citations are forbidden as factual support")
        if cited_kinds and cited_kinds <= SPEC_EVIDENCE_KINDS:
            issues.append(f"{prefix}: exam_specification citations alone cannot support an answer")
        if cited_kinds == {"current_affairs"} and not ((task_context or {}).get("source_policy") or {}).get("allow_pure_current_affairs"):
            issues.append(f"{prefix}: background_current_affairs alone cannot support a non-current-affairs answer")
        roles = item.get("evidence_roles")
        if not isinstance(roles, dict):
            issues.append(f"{prefix}: evidence_roles must be an object")
        else:
            unknown_keys = set(roles) - ITEM_EVIDENCE_ROLE_KEYS
            if unknown_keys:
                issues.append(f"{prefix}: evidence_roles contains unsupported keys {sorted(unknown_keys)}")
            missing_keys = [key for key in ITEM_EVIDENCE_ROLE_ORDER if key not in roles]
            if missing_keys:
                issues.append(f"{prefix}: evidence_roles missing keys {missing_keys}")
            role_ids: set[str] = set()
            for role_key in ITEM_EVIDENCE_ROLE_ORDER:
                values = roles.get(role_key, [])
                if not isinstance(values, list):
                    issues.append(f"{prefix}: evidence_roles.{role_key} must be a list")
                    continue
                for evidence_id in citation_list(values):
                    role_ids.add(evidence_id)
                    ev = evidence_by_id.get(evidence_id)
                    if not ev:
                        issues.append(f"{prefix}: evidence_roles.{role_key} contains unknown evidence id {evidence_id}")
                        continue
                    expected_role = item_role_for_source_kind(ev.source_kind)
                    if expected_role != role_key:
                        issues.append(
                            f"{prefix}: evidence_roles.{role_key} misclassifies {evidence_id}; expected {expected_role}"
                        )
            missing_role_citations = sorted(set(citations) - role_ids)
            if missing_role_citations:
                issues.append(f"{prefix}: evidence_roles must include cited evidence ids {missing_role_citations}")
    return {"ok": not issues, "mode": "policy", "issues": issues}


def validate_review_request(
    *,
    conn: sqlite3.Connection,
    question_id: str,
    decision: str,
    notes: str | None,
) -> None:
    issues: list[str] = []
    row = conn.execute("SELECT status, output_json, verification_json FROM questions WHERE id = ?", (question_id,)).fetchone()
    if not row:
        issues.append(f"question not found: {question_id}")
        require_no_issues(issues)
    if decision == "approved":
        audit = conn.execute(
            """
            SELECT audit_result
            FROM question_similarity_audits
            WHERE question_id = ?
            ORDER BY created_at DESC, compared_at DESC
            LIMIT 1
            """,
            (question_id,),
        ).fetchone()
        if not audit:
            issues.append("cannot approve without a fresh similarity audit")
        elif audit["audit_result"] in BLOCKING_SIMILARITY_RESULTS:
            issues.append(f"cannot approve when similarity audit result is {audit['audit_result']}")
        if row["status"] != "ok":
            issues.append("cannot approve a question run whose status is not ok")
        try:
            output = json.loads(row["output_json"] or "{}")
            verification = json.loads(row["verification_json"] or "{}")
        except json.JSONDecodeError:
            issues.append("cannot approve a question run with invalid stored JSON")
        else:
            if output.get("status") != "ok":
                issues.append("cannot approve refused output")
            if verification.get("ok") is not True:
                issues.append("cannot approve output without passing verification")
    if decision in {"revise", "rejected"} and not str(notes or "").strip():
        issues.append("review notes are required for revise or rejected decisions")
    require_no_issues(issues)


def validate_candidate_review_decision(decision: str, reason_code: str, notes: str) -> None:
    issues: list[str] = []
    if decision not in CANDIDATE_REVIEW_DECISIONS:
        issues.append(f"unsupported candidate review decision: {decision}")
    if reason_code not in CANDIDATE_REASON_CODES:
        issues.append(f"unsupported candidate review reason_code: {reason_code}")
    if not str(notes or "").strip():
        issues.append("candidate review notes are required")
    require_no_issues(issues)


def validate_candidate_approval_gate(conn: sqlite3.Connection, candidate_id: str, decision: str) -> None:
    issues: list[str] = []
    candidate = conn.execute("SELECT id, status FROM candidate_questions WHERE id = ?", (candidate_id,)).fetchone()
    if not candidate:
        issues.append(f"candidate question not found: {candidate_id}")
        require_no_issues(issues)
    if decision != "approved_candidate":
        return
    audit = conn.execute(
        """
        SELECT audit_result
        FROM question_similarity_audits
        WHERE candidate_question_id = ?
        ORDER BY created_at DESC, compared_at DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    if not audit:
        issues.append("candidate approval requires a fresh similarity audit")
    elif audit["audit_result"] in BLOCKING_SIMILARITY_RESULTS:
        issues.append(f"candidate approval blocked by similarity result {audit['audit_result']}")
    require_no_issues(issues)


def approved_items(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT q.id, q.question_type, q.output_json, q.verification_json
        FROM questions q
        WHERE q.task_id = ?
          AND q.status = 'ok'
          AND (
            SELECT r.decision
            FROM question_reviews r
            WHERE r.question_id = q.id
            ORDER BY r.reviewed_at DESC
            LIMIT 1
          ) = 'approved'
        """,
        (task_id,),
    ).fetchall()
    data: list[dict[str, Any]] = []
    for row in rows:
        try:
            output = json.loads(row["output_json"] or "{}")
            verification = json.loads(row["verification_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if output.get("status") != "ok" or verification.get("ok") is not True:
            continue
        for item in output.get("items") or []:
            if isinstance(item, dict):
                data.append({"question_id": row["id"], "question_type": row["question_type"], "item": item})
    return data


def validate_task_completion(conn: sqlite3.Connection, task: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    try:
        validate_task_definition(
            name=task.get("name", ""),
            outline=task.get("outline"),
            source_policy=task.get("source_policy"),
            question_rules=task.get("question_rules"),
            requirements=task.get("requirements"),
            coverage=task.get("coverage"),
            status=task.get("status", ""),
        )
    except ValidationError as exc:
        issues.extend(f"task definition: {issue}" for issue in exc.issues)

    items = approved_items(conn, task["id"])
    coverage = task.get("coverage") or {}
    total_items = coverage.get("total_items")
    if isinstance(total_items, int) and len(items) < total_items:
        issues.append(f"approved item count {len(items)} is below coverage.total_items {total_items}")

    all_points: list[str] = []
    for item in items:
        points = item["item"].get("knowledge_points") or []
        if isinstance(points, str):
            points = [points]
        all_points.extend(str(point) for point in points)
    normalized = [point for point in normalized_point_set(all_points) if point]
    if len(normalized) != len([point for point in all_points if str(point).strip()]):
        issues.append("approved items contain duplicate knowledge_points")

    for row in list_value(coverage, "distribution"):
        if not isinstance(row, dict):
            continue
        target = str(row.get("target") or "")
        qtype = row.get("question_type")
        difficulty = row.get("difficulty")
        needed = int(row.get("count") or 0)
        matched = 0
        for item in items:
            payload = item["item"]
            coverage_target = str(payload.get("coverage_target") or "")
            if item["question_type"] == qtype and payload.get("difficulty") == difficulty and (
                target == coverage_target or target in coverage_target
            ):
                matched += 1
        if matched < needed:
            issues.append(f"coverage target {target} needs {needed} approved items, got {matched}")
    return {"ok": not issues, "issues": issues, "approved_item_count": len(items)}
