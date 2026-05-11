from __future__ import annotations

import json
import re
from typing import Any

from .common import now_iso, stable_id

PROMPT_STAGE_ORDER = [
    "task_definition",
    "source_collection",
    "knowledge_planning",
    "evidence_planning",
    "candidate_writer",
    "candidate_reviewer",
    "similarity_review",
    "final_approval",
]


def build_requirement_prompt_package(
    requirement_text: str,
    *,
    task_name: str | None = None,
    language: str = "zh-CN",
    writer_count: int = 3,
) -> dict[str, Any]:
    text = " ".join(str(requirement_text or "").split())
    if not text:
        raise ValueError("requirement text is required")
    if writer_count <= 0:
        raise ValueError("writer_count must be greater than 0")
    inferred = infer_requirement_hints(text)
    name = task_name or inferred["task_name"]
    package_id = stable_id(name, text, str(writer_count))
    stages = [
        _stage(
            "task_definition",
            "Split the entry requirement into auditable task JSON.",
            [
                "Extract outline, source_policy, question_rules, requirements, and coverage as JSON objects.",
                "Keep uncertain fields explicit in assumptions; do not invent source facts.",
                "Enable review_required, require_citations, and avoid_duplicate_knowledge_points.",
            ],
            {
                "task_name": name,
                "outline": "object",
                "source_policy": "object",
                "question_rules": "object",
                "requirements": "object",
                "coverage": "object",
                "assumptions": [],
            },
            text,
            language,
        ),
        _stage(
            "source_collection",
            "Plan local-first source collection and cache reuse.",
            [
                "List required local files, approved URL sources, and historical_exam sources.",
                "Prefer existing local cache paths before online collection.",
                "Use collect-exam-sources only for historical/prior exam materials.",
            ],
            {
                "local_sources": [],
                "url_sources": [],
                "historical_exam_sources": [],
                "cache_reuse_plan": [],
                "ingest_plan": [],
            },
            text,
            language,
        ),
        _stage(
            "knowledge_planning",
            "Map requirements and outline coverage to knowledge points.",
            [
                "Produce batchable planning units aligned to coverage targets.",
                "Knowledge-point matching may run in parallel with evidence-point generation when sources are indexed.",
                "Keep knowledge points precise enough to avoid repeated testing.",
            ],
            {
                "planning_units": [
                    {
                        "coverage_target": "",
                        "question_type": inferred["question_type"],
                        "difficulty": inferred["difficulty"],
                        "knowledge_points": [],
                    }
                ]
            },
            text,
            language,
        ),
        _stage(
            "evidence_planning",
            "Generate or match evidence points for each knowledge point.",
            [
                "Bind each knowledge point to evidence ids from core/specification sources.",
                "If evidence is missing, produce evidence_gap tasks instead of drafting questions.",
                "Keep current_affairs as background unless the item explicitly tests current affairs.",
            ],
            {
                "evidence_points": [],
                "evidence_gaps": [],
                "parallel_batches": [],
            },
            text,
            language,
        ),
        _stage(
            "candidate_writer",
            "Ask multiple writers to draft distinct candidates for the same planning unit.",
            [
                f"Prepare prompts for {writer_count} writers.",
                "Each writer must use the same evidence bundle but a distinct angle.",
                "Every candidate must include output_json and verification_json before similarity review.",
            ],
            {
                "writer_count": writer_count,
                "writer_prompts": [
                    {
                        "writer_id": f"writer-{idx}",
                        "focus": "distinct angle",
                        "must_use": ["knowledge_points", "evidence_points", "question_rules"],
                    }
                    for idx in range(1, writer_count + 1)
                ],
            },
            text,
            language,
        ),
        _stage(
            "candidate_reviewer",
            "Review candidates against outline, evidence, and item-writing rules.",
            [
                "Approve only candidates with sufficient evidence, distinct knowledge point, and compliant structure.",
                "Route failures to revise_candidate, replan_required, evidence_gap, or rejected_candidate.",
                "Use reason codes such as duplicate_risk_high, evidence_missing, or outline_misalignment.",
            ],
            {
                "review_decisions": [],
                "routing_policy": [
                    "approved_candidate",
                    "revise_candidate",
                    "replan_required",
                    "evidence_gap",
                    "rejected_candidate",
                ],
            },
            text,
            language,
        ),
        _stage(
            "similarity_review",
            "Run local historical duplicate review before approval.",
            [
                "Use audit-question-similarity with a local embedding endpoint.",
                "Compare against historical_exam and question_bank corpora only after generated text exists.",
                "blocked_duplicate and revise_required must block approval.",
            ],
            {
                "commands": [
                    "audit-question-similarity --planning-unit-id PLANNING_UNIT_ID",
                    "audit-question-similarity --question-id QUESTION_ID",
                ],
                "blocking_results": ["blocked_duplicate", "revise_required"],
            },
            text,
            language,
        ),
        _stage(
            "final_approval",
            "Approve final questions only after verification and local similarity review pass.",
            [
                "Use review-question for the final approval record.",
                "Do not mark the task complete until coverage, review, verification, and duplicate gates pass.",
                "Keep rejected or revised candidates auditable.",
            ],
            {
                "approval_gates": [
                    "verification_json.ok is true",
                    "question_similarity_audits.audit_result is pass or pass_with_watch",
                    "review-question decision is approved",
                    "complete-task passes coverage validation",
                ]
            },
            text,
            language,
        ),
    ]
    return {
        "id": package_id,
        "task_name": name,
        "language": language,
        "writer_count": writer_count,
        "created_at": now_iso(),
        "entry_requirement": text,
        "hints": inferred,
        "stages": stages,
    }


def infer_requirement_hints(text: str) -> dict[str, str]:
    question_type = "single_choice"
    if _has_any(text, ["多选", "multiple choice", "multiple_choice"]):
        question_type = "multiple_choice"
    elif _has_any(text, ["简答", "short answer", "short_answer"]):
        question_type = "short_answer"
    elif _has_any(text, ["计算题", "计算", "calculation", "calculation_question"]):
        question_type = "calculation"
    elif _has_any(text, ["材料分析", "material analysis", "material_analysis"]):
        question_type = "material_analysis"

    difficulty = "medium"
    if _has_any(text, ["简单", "easy", "基础"]):
        difficulty = "easy"
    elif _has_any(text, ["困难", "hard", "高难", "拔高"]):
        difficulty = "hard"

    count_match = re.search(r"(\d+)\s*(?:道|题|items?|questions?)", text, re.I)
    count = count_match.group(1) if count_match else ""
    return {
        "task_name": _guess_task_name(text),
        "question_type": question_type,
        "difficulty": difficulty,
        "count": count,
    }


def prompt_package_to_jsonl(package: dict[str, Any]) -> str:
    lines = []
    for stage in package.get("stages") or []:
        lines.append(json.dumps(stage, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def _stage(
    stage_id: str,
    objective: str,
    instructions: list[str],
    expected_output: dict[str, Any],
    entry_requirement: str,
    language: str,
) -> dict[str, Any]:
    prompt = "\n".join(
        [
            f"Stage: {stage_id}",
            f"Objective: {objective}",
            f"Language: {language}",
            "Entry requirement:",
            entry_requirement,
            "Instructions:",
            *[f"- {item}" for item in instructions],
            "Return JSON matching this shape:",
            json.dumps(expected_output, ensure_ascii=False, indent=2),
        ]
    )
    return {
        "stage": stage_id,
        "objective": objective,
        "prompt": prompt,
        "expected_output": expected_output,
        "parallelizable": stage_id in {"knowledge_planning", "evidence_planning", "candidate_writer"},
    }


def _has_any(text: str, needles: list[str]) -> bool:
    lower = text.lower()
    return any(needle.lower() in lower for needle in needles)


def _guess_task_name(text: str) -> str:
    compact = text.strip()
    for separator in ["。", ".", "\n", "；", ";"]:
        if separator in compact:
            compact = compact.split(separator, 1)[0]
            break
    compact = compact[:48].strip()
    return compact or "senior exam writing task"
