from __future__ import annotations

from .common import SOURCE_KINDS

ANSWER_EVIDENCE_KINDS = {"book", "handout", "notes", "qa"}
SPEC_EVIDENCE_KINDS = {"outline", "syllabus", "exam_rules", "requirements"}
PRIOR_STYLE_EVIDENCE_KINDS = {"question_bank", "historical_exam"}

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
SOURCE_KIND_TO_ITEM_ROLE = {
    "book": "core",
    "handout": "core",
    "outline": "specification",
    "syllabus": "specification",
    "exam_rules": "specification",
    "question_bank": "prior_style",
    "historical_exam": "prior_style",
    "qa": "qa",
    "requirements": "specification",
    "current_affairs": "background",
    "notes": "core",
}


def _validated_item_role(source_kind: str) -> str:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"Unsupported source kind: {source_kind}")
    return SOURCE_KIND_TO_ITEM_ROLE[source_kind]


def role_for_source_kind(source_kind: str) -> str:
    return ITEM_ROLE_TO_EVIDENCE_ROLE[_validated_item_role(source_kind)]


def item_role_for_source_kind(source_kind: str) -> str:
    return _validated_item_role(source_kind)


def is_answer_evidence_kind(source_kind: str) -> bool:
    return source_kind in ANSWER_EVIDENCE_KINDS


def is_spec_evidence_kind(source_kind: str) -> bool:
    return source_kind in SPEC_EVIDENCE_KINDS
