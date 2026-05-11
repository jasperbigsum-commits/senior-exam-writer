from __future__ import annotations

import argparse
import json

import pytest

from senior_exam_writer_lib.cli import cmd_generate_candidates
from senior_exam_writer_lib.generation import build_candidate_prompt_record
from senior_exam_writer_lib.store import connect, init_db


def test_candidate_prompt_record_carries_writer_id_and_planning_unit() -> None:
    record = build_candidate_prompt_record(
        writer_id="writer-1",
        planning_unit_id="plan-1",
        topic="\u5171\u540c\u5bcc\u88d5",
        knowledge_points=["\u5171\u540c\u5bcc\u88d5\u7684\u5b9a\u4e49"],
        evidence_points={"\u5171\u540c\u5bcc\u88d5\u7684\u5b9a\u4e49": ["E1", "E2"]},
    )

    assert record["writer_id"] == "writer-1"
    assert record["planning_unit_id"] == "plan-1"
    assert record["evidence_points"] == {"\u5171\u540c\u5bcc\u88d5\u7684\u5b9a\u4e49": ["E1", "E2"]}


def test_candidate_questions_schema_has_auditable_writer_fields(tmp_path) -> None:
    conn = connect(str(tmp_path / "candidate-schema.sqlite"))
    try:
        init_db(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidate_questions)").fetchall()}
    finally:
        conn.close()

    assert {"writer_id", "round", "prompt_json", "output_json", "verification_json"}.issubset(columns)


def test_generate_candidates_persists_writer_fields(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "candidates.sqlite"
    conn = connect(str(db_path))
    try:
        init_db(conn)
        now = "2026-05-11T00:00:00+08:00"
        conn.execute(
            """
            INSERT INTO exam_tasks
            (id, name, outline_json, source_policy_json, question_rules_json, requirements_json, coverage_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "Task 1",
                '{"modules":[]}',
                '{"required_core_kinds":["book"]}',
                '{"question_types":["single_choice"],"require_citations":true,"avoid_duplicate_knowledge_points":true}',
                '{"review_required":true}',
                '{"total_items":1,"distribution":[{"target":"A","question_type":"single_choice","difficulty":"medium","count":1}],"avoid_repeating_knowledge_points":true}',
                "active",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO planning_units
            (
              id, task_id, unit_type, title, objective, coverage_target, question_type, difficulty,
              knowledge_points_json, knowledge_status, evidence_status, writer_round, review_status,
              constraints_json, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plan-1",
                "task-1",
                "knowledge_plan",
                "共同富裕",
                "共同富裕 objective",
                "target-1",
                "single_choice",
                "medium",
                '["共同富裕的定义"]',
                "planned",
                "strong",
                0,
                "pending",
                "{}",
                "{}",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO sources
            (id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("source-1", "book", "Source 1", "source.txt", None, None, None, None, "{}", now),
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
                "Source 1",
                "Source 1",
                "p.1",
                "evidence",
                1,
                "[1.0, 0.0]",
                "{}",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO evidence_points
            (id, planning_unit_id, evidence_id, source_id, chunk_id, support_status, role, claim_text, citation_text, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ep-1",
                "plan-1",
                "E1",
                None,
                None,
                "strong",
                "core_course_evidence",
                "共同富裕的定义",
                "E1",
                "{}",
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("senior_exam_writer_lib.cli.require_embedding_runtime", lambda *_args, **_kwargs: None)

    cmd_generate_candidates(
        argparse.Namespace(
            db=str(db_path),
            planning_unit_id="plan-1",
            topic="共同富裕",
            writer_count=2,
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert [row["writer_id"] for row in payload["candidates"]] == ["writer-1", "writer-2"]

    conn = connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT writer_id, round, prompt_json, output_json, verification_json
            FROM candidate_questions
            ORDER BY writer_id
            """
        ).fetchall()
        unit = conn.execute("SELECT writer_round FROM planning_units WHERE id = ?", ("plan-1",)).fetchone()
    finally:
        conn.close()

    assert [row["writer_id"] for row in rows] == ["writer-1", "writer-2"]
    assert {row["round"] for row in rows} == {1}
    assert json.loads(rows[0]["prompt_json"])["evidence_points"] == {"共同富裕的定义": ["E1"]}
    assert json.loads(rows[0]["output_json"]) == {"status": "pending"}
    assert json.loads(rows[0]["verification_json"]) == {"ok": False, "issues": []}
    assert unit is not None
    assert unit["writer_round"] == 1


def test_generate_candidates_rejects_non_positive_writer_count(tmp_path) -> None:
    with pytest.raises(ValueError):
        cmd_generate_candidates(
            argparse.Namespace(
                db=str(tmp_path / "candidates.sqlite"),
                planning_unit_id="plan-1",
                topic="共同富裕",
                writer_count=0,
            )
        )
