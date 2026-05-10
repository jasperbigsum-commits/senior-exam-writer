from __future__ import annotations

import argparse
import json

import pytest

from senior_exam_writer_lib.cli import cmd_audit_question_similarity
from senior_exam_writer_lib.historical_review import (
    audit_candidate_batch,
    classify_similarity,
    cosine_similarity,
)
from senior_exam_writer_lib.store import connect, init_db


def test_similarity_thresholds_match_review_policy() -> None:
    assert classify_similarity(0.99) == "blocked_duplicate"
    assert classify_similarity(0.95) == "revise_required"
    assert classify_similarity(0.89) == "pass_with_watch"
    assert classify_similarity(0.60) == "pass"


def test_cosine_similarity_handles_zero_vectors() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_audit_candidate_batch_uses_local_embeddings_against_historical_exam(tmp_path) -> None:
    db_path = tmp_path / "historical-review.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_similarity_fixture(conn)
        rows = conn.execute("SELECT * FROM candidate_questions ORDER BY id").fetchall()
        results = audit_candidate_batch(
            conn,
            rows,
            "http://127.0.0.1:8081",
            "local-embedding",
            embedder=lambda texts, _url, _model: [[1.0, 0.0] for _text in texts],
        )
    finally:
        conn.close()

    assert len(results) == 1
    assert results[0]["audit_result"] == "blocked_duplicate"
    assert results[0]["matched_source_kind"] == "historical_exam"
    assert results[0]["matched_chunk_id"] == "chunk-1"


def test_audit_candidate_batch_fails_when_embedding_count_mismatches(tmp_path) -> None:
    db_path = tmp_path / "historical-review-mismatch.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_similarity_fixture(conn)
        _insert_candidate(conn, "candidate-2", "another question stem")
        rows = conn.execute("SELECT * FROM candidate_questions ORDER BY id").fetchall()
        with pytest.raises(ValueError, match="embedding vector count mismatch"):
            audit_candidate_batch(
                conn,
                rows,
                "http://127.0.0.1:8081",
                "local-embedding",
                embedder=lambda texts, _url, _model: [[1.0, 0.0]],
            )
    finally:
        conn.close()


def test_audit_candidate_batch_requires_generated_question_text(tmp_path) -> None:
    db_path = tmp_path / "historical-review-empty.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_similarity_fixture(conn)
        conn.execute("UPDATE candidate_questions SET output_json = ?", ('{"status":"pending"}',))
        conn.commit()
        rows = conn.execute("SELECT * FROM candidate_questions ORDER BY id").fetchall()
        with pytest.raises(ValueError, match="candidate output text is required"):
            audit_candidate_batch(
                conn,
                rows,
                "http://127.0.0.1:8081",
                "local-embedding",
                embedder=lambda texts, _url, _model: [[1.0, 0.0] for _text in texts],
            )
    finally:
        conn.close()


def test_cli_audit_question_similarity_persists_audit_rows(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "historical-review-cli.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_similarity_fixture(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.audit_candidate_batch",
        lambda conn, rows, embed_url, embed_model: __import__(
            "senior_exam_writer_lib.historical_review",
            fromlist=["audit_candidate_batch"],
        ).audit_candidate_batch(
            conn,
            rows,
            embed_url,
            embed_model,
            embedder=lambda texts, _url, _model: [[1.0, 0.0] for _text in texts],
        ),
    )

    cmd_audit_question_similarity(
        argparse.Namespace(
            db=str(db_path),
            planning_unit_id="plan-1",
            question_id=None,
            task_id="task-1",
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["audits"][0]["audit_result"] == "blocked_duplicate"

    conn = connect(str(db_path))
    try:
        audit = conn.execute(
            """
            SELECT task_id, embed_model, audit_result, audit_summary_json
            FROM question_similarity_audits
            """
        ).fetchone()
        hit = conn.execute(
            """
            SELECT matched_source_kind, matched_chunk_id, similarity_score, match_reason
            FROM question_similarity_hits
            """
        ).fetchone()
    finally:
        conn.close()

    assert audit is not None
    assert audit["task_id"] == "task-1"
    assert audit["embed_model"] == "local-embedding"
    assert audit["audit_result"] == "blocked_duplicate"
    assert json.loads(audit["audit_summary_json"])["matched_chunk_id"] == "chunk-1"
    assert hit is not None
    assert hit["matched_source_kind"] == "historical_exam"
    assert hit["matched_chunk_id"] == "chunk-1"
    assert hit["similarity_score"] == 1.0
    assert hit["match_reason"] == "blocked_duplicate"


def test_cli_audit_question_similarity_can_audit_final_question(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "historical-review-question-cli.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        _seed_similarity_fixture(conn)
        conn.execute(
            """
            INSERT INTO questions
            (id, topic, question_type, task_id, prompt_json, evidence_json, output_json, verification_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "question-1",
                "common prosperity",
                "single_choice",
                "task-1",
                "{}",
                "{}",
                '{"status":"ok","items":[{"stem":"historical question stem"}]}',
                '{"ok":true}',
                "ok",
                "2026-05-11T00:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.audit_question_batch",
        lambda conn, rows, embed_url, embed_model: __import__(
            "senior_exam_writer_lib.historical_review",
            fromlist=["audit_question_batch"],
        ).audit_question_batch(
            conn,
            rows,
            embed_url,
            embed_model,
            embedder=lambda texts, _url, _model: [[1.0, 0.0] for _text in texts],
        ),
    )

    cmd_audit_question_similarity(
        argparse.Namespace(
            db=str(db_path),
            planning_unit_id=None,
            question_id="question-1",
            task_id=None,
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["audits"][0]["question_id"] == "question-1"

    conn = connect(str(db_path))
    try:
        audit = conn.execute("SELECT candidate_question_id, question_id, task_id FROM question_similarity_audits").fetchone()
    finally:
        conn.close()

    assert audit is not None
    assert audit["candidate_question_id"] is None
    assert audit["question_id"] == "question-1"
    assert audit["task_id"] == "task-1"


def _seed_similarity_fixture(conn) -> None:
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
        (id, task_id, unit_type, title, objective, coverage_target, question_type, difficulty, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("plan-1", "task-1", "knowledge_plan", "title", "objective", "target", "single_choice", "medium", now, now),
    )
    conn.execute(
        """
        INSERT INTO sources
        (id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("source-1", "historical_exam", "Historical Exam", None, None, None, None, None, "{}", now),
    )
    conn.execute(
        """
        INSERT INTO chunks
        (id, source_id, parent_id, layer, path, title, locator, text, token_count, embedding_json, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "chunk-1",
            "source-1",
            None,
            "content",
            None,
            None,
            None,
            "historical question stem",
            0,
            "[1.0, 0.0]",
            "{}",
            now,
        ),
    )
    _insert_candidate(conn, "candidate-1", "historical question stem")


def _insert_candidate(conn, candidate_id: str, stem: str) -> None:
    now = "2026-05-11T00:00:00+08:00"
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
            candidate_id,
            "task-1",
            "plan-1",
            "single_choice",
            "writer-1",
            1,
            "{}",
            json.dumps({"items": [{"stem": stem}]}),
            '{"ok":true}',
            "pending_review",
            now,
            now,
        ),
    )
    conn.commit()
