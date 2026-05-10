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
