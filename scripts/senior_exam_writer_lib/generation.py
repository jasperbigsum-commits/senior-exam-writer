from __future__ import annotations

import json
import re
from typing import Any

from .common import Evidence
from .llama_cpp_client import llama_chat
from .retrieval import evidence_to_json

def build_generation_prompt(
    topic: str,
    question_type: str,
    count: int,
    difficulty: str,
    evidence: list[Evidence],
    language: str,
) -> list[dict[str, str]]:
    ev_json = evidence_to_json(evidence, max_chars=1600)
    schema = {
        "status": "ok",
        "topic": topic,
        "question_type": question_type,
        "items": [
            {
                "id": "Q1",
                "stem": "...",
                "material": "... optional",
                "options": [{"label": "A", "text": "...", "citations": ["E1"]}],
                "answer": "A",
                "analysis": "...",
                "citations": ["E1", "E2"],
                "assertions": [{"claim": "...", "citations": ["E1"]}],
                "difficulty": difficulty,
                "valid_until": None,
                "evidence_roles": {"core": ["E1"], "background": []},
                "style_profile": {
                    "cognitive_level": "understand",
                    "syllabus_alignment": "cite outline/chapter expectation when available",
                    "stem_style": "clear, exam-grade, no trick wording",
                },
                "difficulty_rationale": "explain why this is easy/medium/hard from outline and evidence",
            }
        ],
    }
    system = (
        "你是资深出题人和严格事实核验员。只能使用用户提供的 evidence JSON 出题。"
        "不得使用常识补充事实，不得编造日期、人名、机构、政策、页码、URL或引用。"
        "教材、讲义、书籍、课程大纲证据是 core_course_evidence；时政、热点、政策新闻素材是 background_current_affairs。"
        "除非用户明确要求纯时政题，否则题目考查点必须优先由 core_course_evidence 支撑，background_current_affairs 只能作为材料背景、案例或辅助解释。"
        "题目风格必须规范、清楚、可考试化；难度必须依据课程大纲、章节要求、证据复杂度和认知层级校准。"
        "证据不足时输出 {\"status\":\"refused\",\"reason\":\"...\",\"missing_evidence\":[...]}。"
    )
    user = f"""
请基于 evidence JSON 生成考试题。

硬性规则：
1. 题干、答案、解析、材料和每个关键断言都必须引用 evidence id。
2. 错误选项必须有明确错因：被证据反驳、偷换概念、主体/时间/范围错误，或 evidence_not_supported。
3. 不要输出 evidence 中没有的事实。
4. current_affairs 证据必须保留来源、日期、URL或文件定位；若可能过时，为题目设置 valid_until 或在 analysis 中说明复检要求。
5. 每道题写 evidence_roles，区分 core 与 background；不要让 background_current_affairs 单独支撑教材知识点答案。
6. 每道题写 style_profile 和 difficulty_rationale；难度不得只凭感觉，必须说明依据：大纲/章节要求、证据数量、概念关系、推理步数、是否涉及应用或分析。
7. 出题风格：题干清楚、条件充分、无无意歧义；选项语法平行、长度相近、只有一个最佳答案；解析按证据解释，不写空泛套话。
8. 只输出 JSON，不要 Markdown。
9. 语言：{language}。

参数：
- topic: {topic}
- question_type: {question_type}
- count: {count}
- difficulty: {difficulty}

必须匹配这个 JSON 形状：
{json.dumps(schema, ensure_ascii=False, indent=2)}

evidence:
{json.dumps(ev_json, ensure_ascii=False, indent=2)}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise

def verify_static(output: dict[str, Any], evidence: list[Evidence]) -> dict[str, Any]:
    evidence_ids = {ev.id for ev in evidence}
    issues: list[str] = []
    if output.get("status") == "refused":
        return {"ok": True, "mode": "static", "issues": [], "refused": True}
    if output.get("status") != "ok":
        issues.append("top-level status must be ok or refused")
    items = output.get("items")
    if not isinstance(items, list) or not items:
        issues.append("items must be a non-empty list")
        return {"ok": False, "mode": "static", "issues": issues}
    for i, item in enumerate(items, 1):
        prefix = f"item {i}"
        for field in ["stem", "answer", "analysis", "citations", "assertions", "style_profile", "difficulty_rationale"]:
            if field not in item:
                issues.append(f"{prefix}: missing {field}")
        style_profile = item.get("style_profile")
        if not isinstance(style_profile, dict):
            issues.append(f"{prefix}: style_profile must be an object")
        else:
            for field in ["cognitive_level", "syllabus_alignment", "stem_style"]:
                if not style_profile.get(field):
                    issues.append(f"{prefix}: style_profile missing {field}")
        if not item.get("difficulty_rationale"):
            issues.append(f"{prefix}: missing difficulty_rationale")
        citations = item.get("citations") or []
        if not isinstance(citations, list) or not citations:
            issues.append(f"{prefix}: citations must be a non-empty list")
        else:
            bad = [c for c in citations if c not in evidence_ids]
            if bad:
                issues.append(f"{prefix}: unknown citations {bad}")
        assertions = item.get("assertions") or []
        if not isinstance(assertions, list) or not assertions:
            issues.append(f"{prefix}: assertions must be a non-empty list")
        for aidx, assertion in enumerate(assertions, 1):
            ac = assertion.get("citations") if isinstance(assertion, dict) else None
            claim = assertion.get("claim") if isinstance(assertion, dict) else None
            if not claim:
                issues.append(f"{prefix} assertion {aidx}: missing claim")
            if not ac or not isinstance(ac, list):
                issues.append(f"{prefix} assertion {aidx}: missing citations")
            else:
                bad = [c for c in ac if c not in evidence_ids]
                if bad:
                    issues.append(f"{prefix} assertion {aidx}: unknown citations {bad}")
        if item.get("options"):
            labels = [opt.get("label") for opt in item["options"] if isinstance(opt, dict)]
            if item.get("answer") not in labels:
                issues.append(f"{prefix}: answer is not one of option labels")
    return {"ok": not issues, "mode": "static", "issues": issues}

def verify_with_llm(
    output: dict[str, Any],
    evidence: list[Evidence],
    llm_url: str,
    llm_model: str,
) -> dict[str, Any]:
    static = verify_static(output, evidence)
    if not static["ok"] or output.get("status") == "refused":
        return static
    messages = [
        {
            "role": "system",
            "content": (
                "你是严格证据核验器。只判断题目 JSON 中每个断言是否被 evidence 支持。"
                "输出 JSON: {\"ok\":true/false,\"issues\":[...],\"item_results\":[...]}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "verify_exam_items_against_evidence",
                    "evidence": evidence_to_json(evidence, max_chars=1800),
                    "output": output,
                    "rules": [
                        "unsupported or contradicted assertions are failures",
                        "missing citations are failures",
                        "answer key inconsistent with evidence is a failure",
                        "do not repair; only verify",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]
    raw = llama_chat(messages, llm_url, llm_model, temperature=0.0, max_tokens=2048)
    try:
        llm_report = extract_json(raw)
    except Exception:
        return {"ok": False, "mode": "llm", "issues": ["verifier returned non-JSON", raw[:800]], "static": static}
    if not isinstance(llm_report, dict):
        return {"ok": False, "mode": "llm", "issues": ["verifier returned non-object JSON"], "static": static}
    llm_report["static"] = static
    llm_report["mode"] = "llm"
    llm_report["ok"] = bool(llm_report.get("ok")) and static["ok"]
    return llm_report

def refusal(topic: str, gate: dict[str, Any], evidence: list[Evidence]) -> dict[str, Any]:
    return {
        "status": "refused",
        "topic": topic,
        "reason": "evidence_gate_failed",
        "missing_evidence": gate.get("issues", []),
        "strongest_evidence": evidence_to_json(evidence[:5], max_chars=700),
    }

def rewrite_once(
    output: dict[str, Any],
    verification: dict[str, Any],
    topic: str,
    question_type: str,
    count: int,
    difficulty: str,
    evidence: list[Evidence],
    language: str,
    llm_url: str,
    llm_model: str,
) -> dict[str, Any]:
    messages = build_generation_prompt(topic, question_type, count, difficulty, evidence, language)
    messages.append(
        {
            "role": "user",
            "content": (
                "上一次输出未通过核验。请只使用同一份 evidence 重写，修复所有问题。"
                "如果无法修复，输出 refused JSON。\n\n"
                f"verification:\n{json.dumps(verification, ensure_ascii=False, indent=2)}\n\n"
                f"previous_output:\n{json.dumps(output, ensure_ascii=False, indent=2)}"
            ),
        }
    )
    raw = llama_chat(messages, llm_url, llm_model, temperature=0.1, max_tokens=4096)
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("rewrite returned non-object JSON")
    return parsed

