from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from senior_exam_writer_lib.cli import cmd_init_runtime
from senior_exam_writer_lib.runtime import ensure_local_base_url, init_runtime_layout
from senior_exam_writer_lib.validation import ValidationError


def test_only_loopback_urls_are_allowed() -> None:
    assert ensure_local_base_url("http://127.0.0.1:8081").hostname == "127.0.0.1"

    with pytest.raises(ValueError):
        ensure_local_base_url("https://api.openai.com/v1")


def test_init_runtime_layout_creates_sidecar_dirs(tmp_path: Path) -> None:
    manifest = init_runtime_layout(tmp_path / "exam.sqlite", sidecar_root=tmp_path)

    downloads_dir = tmp_path / ".senior-exam-writer" / "exam" / "downloads"
    reports_dir = tmp_path / ".senior-exam-writer" / "exam" / "reports"

    assert downloads_dir.is_dir()
    assert reports_dir.is_dir()
    assert manifest["paths"]["db"] == str((tmp_path / "exam.sqlite").resolve())


def test_init_runtime_exits_nonzero_when_probe_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.probe_json",
        lambda url: {"ok": False, "url": url, "error": "connection refused"},
    )
    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.probe_embedding_endpoint",
        lambda url, model: {"ok": False, "url": url, "model": model, "error": "connection refused"},
    )
    args = argparse.Namespace(
        db=str(tmp_path / "exam.sqlite"),
        sidecar_root=str(tmp_path),
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        llm_url="",
        llm_model="local-instruct",
    )

    with pytest.raises(SystemExit) as exc:
        cmd_init_runtime(args)

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["embed_probe"]["ok"] is False
    assert payload["llm_required"] is False
    assert payload["llm_probe"] is None


def test_init_runtime_treats_llm_probe_as_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.probe_json",
        lambda url: {"ok": True, "url": url},
    )
    monkeypatch.setattr(
        "senior_exam_writer_lib.cli.probe_embedding_endpoint",
        lambda url, model: {"ok": True, "url": url, "model": model, "dimension": 1024},
    )

    args = argparse.Namespace(
        db=str(tmp_path / "exam.sqlite"),
        sidecar_root=str(tmp_path),
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
        llm_url="",
        llm_model="local-instruct",
    )

    cmd_init_runtime(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["embed_probe"]["ok"] is True
    assert payload["llm_probe"] is None
    assert payload["llm_required"] is False


def test_commands_that_use_embeddings_reject_remote_urls() -> None:
    from senior_exam_writer_lib.cli import validate_embed_endpoint_when_used

    with pytest.raises(ValidationError):
        validate_embed_endpoint_when_used(True, "https://api.example.com")

    validate_embed_endpoint_when_used(False, "https://api.example.com")


def test_ingest_requires_embeddings_and_reports_policy_error() -> None:
    from senior_exam_writer_lib.cli import require_ingest_embeddings

    args = argparse.Namespace(
        embed=False,
        embed_url="http://127.0.0.1:8081",
        embed_model="local-embedding",
    )

    with pytest.raises(ValidationError) as exc:
        require_ingest_embeddings(args)

    assert any("--no-embed is disabled" in issue for issue in exc.value.issues)


def test_json_argument_files_accept_utf8_bom(tmp_path: Path) -> None:
    from senior_exam_writer_lib.tasks import read_json_arg

    json_path = tmp_path / "outline.json"
    json_path.write_text('{"modules":[{"name":"\\u7ecf\\u6d4e\\u7edf\\u8ba1\\u5b66"}]}', encoding="utf-8-sig")

    assert read_json_arg(str(json_path), "outline") == {"modules": [{"name": "\u7ecf\u6d4e\u7edf\u8ba1\u5b66"}]}


def test_json_arguments_tolerate_common_shell_escaping() -> None:
    from senior_exam_writer_lib.tasks import read_json_arg

    expected = {"modules": [{"name": "math"}]}
    assert read_json_arg('{"modules":[{"name":"math"}]}', "outline") == expected
    assert read_json_arg('"{\\"modules\\":[{\\"name\\":\\"math\\"}]}"', "outline") == expected
    assert read_json_arg('{\\"modules\\":[{\\"name\\":\\"math\\"}]}', "outline") == expected
    assert read_json_arg('{""modules"":[{""name"":""math""}]}', "outline") == expected
    assert read_json_arg("{'modules':[{'name':'math'}]}", "outline") == expected


def test_task_definition_accepts_calculation_question_type() -> None:
    from senior_exam_writer_lib.validation import validate_task_definition

    validate_task_definition(
        name="calculation task",
        outline={"modules": [{"name": "math", "objectives": ["variance"]}]},
        source_policy={"required_core_kinds": ["book"]},
        question_rules={
            "question_types": ["calculation", "short_answer"],
            "require_citations": True,
            "avoid_duplicate_knowledge_points": True,
        },
        requirements={"review_required": True},
        coverage={
            "total_items": 1,
            "distribution": [
                {
                    "target": "math/variance",
                    "question_type": "calculation",
                    "difficulty": "medium",
                    "count": 1,
                }
            ],
            "avoid_repeating_knowledge_points": True,
        },
        status="active",
    )


def test_vectorized_corpus_blocks_unembedded_chunks(tmp_path: Path) -> None:
    import sqlite3

    from senior_exam_writer_lib.cli import require_vectorized_corpus
    from senior_exam_writer_lib.store import init_db

    db_path = tmp_path / "unembedded.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        now = "2026-05-11T00:00:00+08:00"
        conn.execute(
            """
            INSERT INTO sources
            (id, kind, title, path, source_name, url, published_at, version, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("source-1", "book", "Book", "book.txt", None, None, None, None, "{}", now),
        )
        conn.execute(
            """
            INSERT INTO chunks
            (id, source_id, parent_id, layer, path, title, locator, text, token_count, embedding_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("chunk-1", "source-1", None, "content", "Book", "Book", "p.1", "text", 1, None, "{}", now),
        )
        conn.commit()

        with pytest.raises(ValidationError) as exc:
            require_vectorized_corpus(conn)
    finally:
        conn.close()

    assert any("unembedded_chunks=1/1" in issue for issue in exc.value.issues)
