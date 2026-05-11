from __future__ import annotations

from senior_exam_writer_lib.common import Evidence
from senior_exam_writer_lib.generation import verify_static
from senior_exam_writer_lib.validation import validate_output_contract


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id="E1",
            chunk_id="chunk-1",
            source_id="source-1",
            layer="parent",
            path="sample variance",
            title="sample variance",
            locator="p.1",
            text="Unbiased sample variance uses n-1 as the denominator.",
            score=0.99,
            source_kind="book",
            source_title="Statistics",
            source_path="statistics.md",
            source_name=None,
            source_url=None,
            published_at=None,
        )
    ]


def _task_context() -> dict[str, object]:
    return {
        "coverage": {
            "distribution": [
                {
                    "target": "statistics/sample variance",
                    "question_type": "calculation",
                    "difficulty": "medium",
                    "count": 1,
                }
            ]
        },
        "source_policy": {"required_core_kinds": ["book"]},
    }


def _calculation_output() -> dict[str, object]:
    return {
        "status": "ok",
        "topic": "sample variance",
        "question_type": "calculation",
        "items": [
            {
                "id": "Q1",
                "stem": "Compute an unbiased sample variance.",
                "answer": "Use n-1 in the denominator.",
                "analysis": "The cited formula requires n-1 for an unbiased sample variance.",
                "citations": ["E1"],
                "assertions": [{"claim": "Unbiased sample variance uses n-1.", "citations": ["E1"]}],
                "solution_steps": [{"step": "Apply the unbiased sample variance formula.", "citations": ["E1"]}],
                "formula_reference": "Unbiased sample variance formula, cited by E1.",
                "knowledge_points": ["unbiased sample variance denominator"],
                "coverage_target": "statistics/sample variance",
                "difficulty": "medium",
                "evidence_roles": {
                    "core": ["E1"],
                    "background": [],
                    "specification": [],
                    "prior_style": [],
                    "qa": [],
                },
                "style_profile": {
                    "cognitive_level": "apply",
                    "syllabus_alignment": "statistics/sample variance",
                    "stem_style": "clear calculation task",
                },
                "difficulty_rationale": "Medium because it applies a formula rather than recalling a term.",
                "dedup_check": {
                    "against_prior_task_items": "No prior item uses this point.",
                    "within_batch": "Only one item in this batch.",
                },
            }
        ],
    }


def test_calculation_output_contract_requires_solution_steps_and_formula_reference() -> None:
    output = _calculation_output()

    assert verify_static(output, _evidence())["ok"] is True
    assert validate_output_contract(
        output=output,
        evidence=_evidence(),
        task_context=_task_context(),
        question_type="calculation",
        count=1,
        difficulty="medium",
    )["ok"] is True

    broken = _calculation_output()
    item = broken["items"][0]
    assert isinstance(item, dict)
    item.pop("solution_steps")
    item.pop("formula_reference")

    static = verify_static(broken, _evidence())
    policy = validate_output_contract(
        output=broken,
        evidence=_evidence(),
        task_context=_task_context(),
        question_type="calculation",
        count=1,
        difficulty="medium",
    )
    assert static["ok"] is False
    assert "missing solution_steps" in "; ".join(static["issues"])
    assert policy["ok"] is False
    joined = "; ".join(policy["issues"])
    assert "calculation requires solution_steps" in joined
    assert "calculation requires formula_reference" in joined
