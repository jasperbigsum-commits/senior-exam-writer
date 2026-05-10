from __future__ import annotations

import argparse
import sqlite3

from senior_exam_writer_lib.cli import cmd_plan_evidence, cmd_plan_knowledge
from senior_exam_writer_lib.evidence_planning import classify_support
from senior_exam_writer_lib.planning import build_planning_units
from senior_exam_writer_lib.store import init_db


TARGET = "\u6a21\u5757\u4e00/\u6982\u5ff5A"
OBJECTIVE = "\u6a21\u5757\u4e00 objective \u6982\u5ff5A"
POINT_ONE = "\u77e5\u8bc6\u70b9\u4e00"
POINT_TWO = "\u77e5\u8bc6\u70b9\u4e8c"


def test_build_planning_units_from_coverage() -> None:
    task = {
        "id": "task-1",
        "coverage": {
            "distribution": [
                {
                    "target": TARGET,
                    "question_type": "single_choice",
                    "difficulty": "medium",
                    "count": 2,
                }
            ]
        },
        "outline": {
            "modules": [
                {
                    "name": "\u6a21\u5757\u4e00",
                    "objectives": ["\u6982\u5ff5A"],
                }
            ]
        },
    }

    units = build_planning_units(task)

    assert len(units) == 2
    assert units[0]["coverage_target"] == TARGET
    assert units[0]["objective"] == OBJECTIVE


def test_classify_support_prefers_strong_when_each_point_has_evidence() -> None:
    mapping = {
        POINT_ONE: ["ev-1"],
        POINT_TWO: ["ev-2"],
    }

    assert classify_support(mapping) == "strong"


def test_cli_plan_commands_persist_objective_and_ignore_non_knowledge_units(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "planning.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO exam_tasks
            (id, name, outline_json, source_policy_json, question_rules_json, requirements_json, coverage_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "Task 1",
                '{"modules":[{"name":"\\u6a21\\u5757\\u4e00","objectives":["\\u6982\\u5ff5A"]}]}',
                '{"required_core_kinds":["book"]}',
                '{"question_types":["single_choice"],"require_citations":true,"avoid_duplicate_knowledge_points":true}',
                '{"review_required":true}',
                '{"total_items":2,"distribution":[{"target":"\\u6a21\\u5757\\u4e00/\\u6982\\u5ff5A","question_type":"single_choice","difficulty":"medium","count":2}],"avoid_repeating_knowledge_points":true}',
                "active",
                "2026-05-11T00:00:00+00:00",
                "2026-05-11T00:00:00+00:00",
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
                "style-unit",
                "task-1",
                "style_plan",
                "style title",
                "style objective",
                "style target",
                "single_choice",
                "medium",
                "[]",
                "planned",
                "pending",
                0,
                "pending",
                "{}",
                "{}",
                "2026-05-11T00:00:00+00:00",
                "2026-05-11T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO sources
            (id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "source-1",
                "book",
                "Source 1",
                None,
                None,
                None,
                None,
                None,
                "{}",
                "2026-05-11T00:00:00+00:00",
            ),
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
                "parent",
                None,
                None,
                None,
                "example",
                0,
                None,
                "{}",
                "2026-05-11T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    cmd_plan_knowledge(argparse.Namespace(db=str(db_path), task_id="task-1"))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT objective FROM planning_units WHERE task_id = ? AND unit_type = 'knowledge_plan' ORDER BY created_at, id LIMIT 1",
            ("task-1",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["objective"] == OBJECTIVE

    def fake_collect_evidence_bundle(
        _conn: sqlite3.Connection,
        unit: dict[str, object],
        _embed_url: str,
        _embed_model: str,
    ) -> dict[str, object]:
        return {
            "mapping": {POINT_ONE: ["ev-1"]},
            "records": {
                POINT_ONE: [
                    {
                        "evidence_id": "ev-1",
                        "chunk_id": "chunk-1",
                        "source_id": "source-1",
                    }
                ]
            },
        }

    monkeypatch.setattr("senior_exam_writer_lib.cli._collect_evidence_bundle", fake_collect_evidence_bundle)

    cmd_plan_evidence(
        argparse.Namespace(
            db=str(db_path),
            task_id="task-1",
            embed_url="http://127.0.0.1:8081",
            embed_model="local-embedding",
        )
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        knowledge_status = conn.execute(
            "SELECT evidence_status FROM planning_units WHERE task_id = ? AND unit_type = 'knowledge_plan' ORDER BY created_at, id LIMIT 1",
            ("task-1",),
        ).fetchone()
        style_status = conn.execute(
            "SELECT evidence_status FROM planning_units WHERE id = ?",
            ("style-unit",),
        ).fetchone()
        evidence_rows = conn.execute(
            "SELECT planning_unit_id, evidence_id, source_id, chunk_id, support_status FROM evidence_points ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert knowledge_status is not None
    assert knowledge_status["evidence_status"] == "strong"
    assert style_status is not None
    assert style_status["evidence_status"] == "pending"
    assert len(evidence_rows) == 2
    assert all(row["planning_unit_id"] != "style-unit" for row in evidence_rows)
