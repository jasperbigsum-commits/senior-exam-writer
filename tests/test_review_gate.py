from __future__ import annotations

import argparse
import json

import pytest

from senior_exam_writer_lib.cli import cmd_review_candidate
from senior_exam_writer_lib.store import connect, init_db
from senior_exam_writer_lib.validation import (
    ValidationError,
    validate_candidate_approval_gate,
    validate_candidate_review_decision,
    validate_review_request,
)


def test_candidate_review_accepts_only_known_reason_codes() -> None:
    validate_candidate_review_decision("revise_candidate", "writer_quality_issue", "rewrite from a new angle")
    with pytest.raises(ValidationError):
        validate_candidate_review_decision("revise_candidate", "unknown_reason", "bad code")


def test_candidate_approval_requires_passing_similarity_audit(tmp_path) -> None:
    db_path = tmp_path / "review-gate.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_candidate_review_fixture(conn)
        with pytest.raises(ValidationError) as missing:
            validate_candidate_approval_gate(conn, "candidate-1", "approved_candidate")
        assert "fresh similarity audit" in str(missing.value)

        conn.execute(
            """
            INSERT INTO question_similarity_audits
            (
              id, candidate_question_id, question_id, task_id, embed_model, embed_url,
              threshold_policy_json, audit_result, audit_summary_json,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-1",
                "candidate-1",
                None,
                "task-1",
                "local-embedding",
                "http://127.0.0.1:8081",
                "{}",
                "revise_required",
                "{}",
                "2026-05-11T00:00:01+08:00",
            ),
        )
        conn.commit()
        with pytest.raises(ValidationError) as blocked:
            validate_candidate_approval_gate(conn, "candidate-1", "approved_candidate")
    finally:
        conn.close()

    assert "revise_required" in str(blocked.value)


def test_review_candidate_routes_evidence_gap_to_planning_unit(tmp_path, capsys) -> None:
    db_path = tmp_path / "review-candidate.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_candidate_review_fixture(conn)
    finally:
        conn.close()

    cmd_review_candidate(
        argparse.Namespace(
            db=str(db_path),
            candidate_id="candidate-1",
            reviewer="chief-reviewer",
            decision="evidence_gap",
            reason_code="evidence_missing",
            notes="needs more citations before another writer round",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["review"]["decision"] == "evidence_gap"

    conn = connect(str(db_path))
    try:
        candidate = conn.execute("SELECT status FROM candidate_questions WHERE id = ?", ("candidate-1",)).fetchone()
        unit = conn.execute("SELECT review_status FROM planning_units WHERE id = ?", ("plan-1",)).fetchone()
        review = conn.execute("SELECT reason_code, review_json FROM candidate_reviews").fetchone()
    finally:
        conn.close()

    assert candidate is not None
    assert candidate["status"] == "evidence_gap"
    assert unit is not None
    assert unit["review_status"] == "evidence_gap"
    assert review is not None
    assert review["reason_code"] == "evidence_missing"
    assert json.loads(review["review_json"])["route"] == "evidence_missing"


def test_question_approval_requires_similarity_audit(tmp_path) -> None:
    db_path = tmp_path / "question-review-gate.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_question_review_fixture(conn)
        with pytest.raises(ValidationError) as missing:
            validate_review_request(conn=conn, question_id="question-1", decision="approved", notes=None)
        assert "fresh similarity audit" in str(missing.value)

        conn.execute(
            """
            INSERT INTO question_similarity_audits
            (
              id, candidate_question_id, question_id, task_id, embed_model, embed_url,
              threshold_policy_json, audit_result, audit_summary_json,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-1",
                "candidate-1",
                "question-1",
                "task-1",
                "local-embedding",
                "http://127.0.0.1:8081",
                "{}",
                "pass",
                "{}",
                "2026-05-11T00:00:01+08:00",
            ),
        )
        conn.commit()
        validate_review_request(conn=conn, question_id="question-1", decision="approved", notes=None)
    finally:
        conn.close()


def _seed_candidate_review_fixture(conn) -> None:
    now = "2026-05-11T00:00:00+08:00"
    conn.execute(
        """
        INSERT INTO exam_tasks
        (id, name, outline_json, source_policy_json, question_rules_json, requirements_json, coverage_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("task-1", "Task 1", "{}", "{}", "{}", "{}", "{}", "active", now, now),
    )
    conn.execute(
        """
        INSERT INTO planning_units
        (id, task_id, unit_type, title, objective, coverage_target, question_type, difficulty, review_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("plan-1", "task-1", "knowledge_plan", "title", "objective", "target", "single_choice", "medium", "pending", now, now),
    )
    conn.execute(
        """
        INSERT INTO candidate_questions
        (
          id, task_id, planning_unit_id, question_type, writer_id, round,
          prompt_json, output_json, verification_json, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "candidate-1",
            "task-1",
            "plan-1",
            "single_choice",
            "writer-1",
            1,
            "{}",
            '{"items":[{"stem":"example"}]}',
            '{"ok":true}',
            "pending_review",
            now,
            now,
        ),
    )
    conn.commit()


def _seed_question_review_fixture(conn) -> None:
    _seed_candidate_review_fixture(conn)
    now = "2026-05-11T00:00:00+08:00"
    conn.execute(
        """
        INSERT INTO questions
        (id, topic, question_type, task_id, prompt_json, evidence_json, output_json, verification_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "question-1",
            "topic",
            "single_choice",
            "task-1",
            "{}",
            "{}",
            '{"status":"ok","items":[{"stem":"example"}]}',
            '{"ok":true}',
            "ok",
            now,
        ),
    )
    conn.commit()
