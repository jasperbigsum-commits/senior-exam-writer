from __future__ import annotations

import sqlite3

from senior_exam_writer_lib.common import SOURCE_KINDS
from senior_exam_writer_lib.evidence_roles import (
    ROLE_PRIOR_STYLE,
    item_role_for_source_kind,
    role_for_source_kind,
)
from senior_exam_writer_lib.store import init_db


def test_historical_exam_source_kind_is_supported() -> None:
    assert "historical_exam" in SOURCE_KINDS


def test_historical_exam_uses_prior_style_roles() -> None:
    assert item_role_for_source_kind("historical_exam") == "prior_style"
    assert role_for_source_kind("historical_exam") == ROLE_PRIOR_STYLE


def test_unknown_source_kind_is_rejected() -> None:
    try:
        role_for_source_kind("mystery_kind")
    except ValueError as exc:
        assert "Unsupported source kind" in str(exc)
    else:
        raise AssertionError("Unsupported source kind should raise ValueError")


def test_extended_review_tables_exist() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "fetch_cache",
        "planning_units",
        "evidence_points",
        "candidate_questions",
        "candidate_reviews",
        "question_similarity_audits",
        "question_similarity_hits",
    }.issubset(table_names)


def test_similarity_audit_can_target_final_question_without_candidate() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        columns = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(question_similarity_audits)").fetchall()
        }
    finally:
        conn.close()

    assert columns["candidate_question_id"][3] == 0
    assert "question_id" in columns


def test_candidate_reviews_accept_route_decision_values() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        now = "2026-05-11T00:00:00+08:00"
        conn.execute(
            """
            INSERT INTO exam_tasks
            (id, name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("task-1", "Task 1", "active", now, now),
        )
        conn.execute(
            """
            INSERT INTO planning_units
            (id, task_id, unit_type, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("plan-1", "task-1", "knowledge_plan", "title", now, now),
        )
        conn.execute(
            """
            INSERT INTO candidate_questions
            (id, task_id, planning_unit_id, question_type, prompt_text, draft_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("candidate-1", "task-1", "plan-1", "single_choice", "{}", "{}", "pending_review", now, now),
        )
        conn.execute(
            """
            INSERT INTO candidate_reviews
            (id, candidate_question_id, decision, reason_code, notes, review_json, patch_json, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "review-1",
                "candidate-1",
                "evidence_gap",
                "evidence_missing",
                "needs evidence backfill",
                "{}",
                "{}",
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT decision FROM candidate_reviews WHERE id = ?", ("review-1",)).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "evidence_gap"


def test_init_db_adds_legacy_questions_task_id_without_foreign_key() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE exam_tasks (
              id TEXT PRIMARY KEY
            );

            CREATE TABLE questions (
              id TEXT PRIMARY KEY,
              topic TEXT NOT NULL,
              question_type TEXT NOT NULL,
              prompt_json TEXT NOT NULL,
              evidence_json TEXT NOT NULL,
              output_json TEXT NOT NULL,
              verification_json TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        init_db(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        foreign_keys = conn.execute("PRAGMA foreign_key_list(questions)").fetchall()
    finally:
        conn.close()

    assert "task_id" in columns
    assert foreign_keys == []


def test_init_db_fresh_questions_table_has_task_id_foreign_key() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        foreign_keys = conn.execute("PRAGMA foreign_key_list(questions)").fetchall()
    finally:
        conn.close()

    assert any(row[2] == "exam_tasks" and row[3] == "task_id" for row in foreign_keys)
