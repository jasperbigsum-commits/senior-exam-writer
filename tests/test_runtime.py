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

    args = argparse.Namespace(
        db=str(tmp_path / "exam.sqlite"),
        sidecar_root=str(tmp_path),
        embed_url="http://127.0.0.1:8081",
        llm_url="http://127.0.0.1:8080",
    )

    with pytest.raises(SystemExit) as exc:
        cmd_init_runtime(args)

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["embed_probe"]["ok"] is False
    assert payload["llm_probe"]["ok"] is False


def test_commands_that_use_embeddings_reject_remote_urls() -> None:
    from senior_exam_writer_lib.cli import validate_embed_endpoint_when_used

    with pytest.raises(ValidationError):
        validate_embed_endpoint_when_used(True, "https://api.example.com")

    validate_embed_endpoint_when_used(False, "https://api.example.com")
