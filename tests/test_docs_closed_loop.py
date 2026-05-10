from __future__ import annotations

from pathlib import Path


def test_skill_docs_mention_closed_loop_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    joined = "\n".join(
        [
            (root / "SKILL.md").read_text(encoding="utf-8"),
            (root / "references" / "task_workflow.md").read_text(encoding="utf-8"),
        ]
    )
    for token in [
        "init-runtime",
        "split-requirements",
        "collect-exam-sources",
        "--input",
        "--ingest",
        "plan-knowledge",
        "plan-evidence",
        "generate-candidates",
        "audit-question-similarity",
        "review-candidate",
    ]:
        assert token in joined


def test_runtime_setup_has_single_cli_entrypoint() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "scripts" / "init_local_runtime.py").exists()


def test_acceptance_checklist_is_discoverable() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    checklist = (root / "references" / "acceptance_checklist.md").read_text(encoding="utf-8")

    assert "references/acceptance_checklist.md" in skill
    for token in [
        "Civil-Service Exam",
        "University Final",
        "AI Engineer Hiring Assessment",
        "Flow compliance",
        "Evidence completeness",
    ]:
        assert token in checklist
