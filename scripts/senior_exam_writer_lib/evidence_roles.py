from __future__ import annotations

ANSWER_EVIDENCE_KINDS = {"book", "handout", "notes", "qa"}
SPEC_EVIDENCE_KINDS = {"outline", "syllabus", "exam_rules", "requirements"}

ROLE_CORE = "core_course_evidence"
ROLE_SPEC = "exam_specification"
ROLE_PRIOR_STYLE = "prior_question_style"
ROLE_QA = "supplemental_qa_evidence"
ROLE_CURRENT = "background_current_affairs"

ITEM_EVIDENCE_ROLE_ORDER = ("core", "background", "specification", "prior_style", "qa")
ITEM_EVIDENCE_ROLE_KEYS = {"core", "background", "specification", "prior_style", "qa"}
ITEM_ROLE_TO_EVIDENCE_ROLE = {
    "core": ROLE_CORE,
    "background": ROLE_CURRENT,
    "specification": ROLE_SPEC,
    "prior_style": ROLE_PRIOR_STYLE,
    "qa": ROLE_QA,
}


def role_for_source_kind(source_kind: str) -> str:
    if source_kind == "current_affairs":
        return ROLE_CURRENT
    if source_kind in SPEC_EVIDENCE_KINDS:
        return ROLE_SPEC
    if source_kind == "question_bank":
        return ROLE_PRIOR_STYLE
    if source_kind == "qa":
        return ROLE_QA
    return ROLE_CORE


def item_role_for_source_kind(source_kind: str) -> str:
    if source_kind == "current_affairs":
        return "background"
    if source_kind in SPEC_EVIDENCE_KINDS:
        return "specification"
    if source_kind == "question_bank":
        return "prior_style"
    if source_kind == "qa":
        return "qa"
    return "core"


def is_answer_evidence_kind(source_kind: str) -> bool:
    return source_kind in ANSWER_EVIDENCE_KINDS


def is_spec_evidence_kind(source_kind: str) -> bool:
    return source_kind in SPEC_EVIDENCE_KINDS
