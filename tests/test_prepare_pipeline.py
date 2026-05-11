from __future__ import annotations

import argparse
import json

from senior_exam_writer_lib.cli import cmd_prepare_pipeline


def test_prepare_pipeline_batches_without_embedding_runtime(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "materials"
    nested = source_root / "chapter1"
    nested.mkdir(parents=True)
    material = nested / "material.md"
    material.write_text(
        "# 第一章 导论\n共同富裕是社会主义现代化的重要目标。\n# 第二章 方法\n数量关系题需要清晰条件。",
        encoding="utf-8",
    )
    output_dir = tmp_path / "prepared"

    def fail_if_embedding_called(*_args, **_kwargs):
        raise AssertionError("prepare-pipeline must not call embedding runtime")

    monkeypatch.setattr("senior_exam_writer_lib.cli.require_embedding_runtime", fail_if_embedding_called)
    monkeypatch.setattr("senior_exam_writer_lib.llama_cpp_client.llama_embed", fail_if_embedding_called)

    cmd_prepare_pipeline(
        argparse.Namespace(
            requirements="根据材料生成期末考试题，包含简答题和计算题。",
            requirements_file=None,
            input=[str(source_root)],
            output_dir=str(output_dir),
            db=str(tmp_path / "exam.sqlite"),
            task_name="prepare test",
            language="zh-CN",
            writer_count=2,
            embed_url="http://127.0.0.1:8081",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "prepare_only_no_embedding"
    assert payload["source_manifest"][0]["status"] == "ok"
    assert "ingest --embed" in payload["blocked_until_embedding_ready"]

    first_source = payload["source_manifest"][0]
    assert first_source["connector_plan"]["connector"] == "markdown_reader"
    assert first_source["archive_relative_path"].replace("\\", "/") == "chapter1/material.md"
    assert (output_dir / "original_sources" / "chapter1" / "material.md").exists()

    for filename in [
        "prompt_package.json",
        "prompt_stages.jsonl",
        "source_manifest.json",
        "outline.json",
        "source_policy.json",
        "question_rules.json",
        "requirements.json",
        "coverage.json",
        "prepare_report.json",
        "next_commands.ps1",
    ]:
        assert (output_dir / filename).exists()

    requirements = json.loads((output_dir / "requirements.json").read_text(encoding="utf-8"))
    assert requirements["prepare_only"] is True
    assert requirements["must_run_embedding_stage_before_citation_use"] is True

    next_commands = (output_dir / "next_commands.ps1").read_text(encoding="utf-8")
    assert "init-runtime" in next_commands
    assert "plan-evidence" in next_commands


def test_prepare_pipeline_next_commands_are_powershell_safe(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "材料 source"
    source_root.mkdir()
    material = source_root / "高等数学's (统计).md"
    material.write_text("# sample\ntext", encoding="utf-8")
    output_dir = tmp_path / "prepared output's"
    db_path = tmp_path / "exam db's.sqlite"

    def fail_if_embedding_called(*_args, **_kwargs):
        raise AssertionError("prepare-pipeline must not call embedding runtime")

    monkeypatch.setattr("senior_exam_writer_lib.cli.require_embedding_runtime", fail_if_embedding_called)
    monkeypatch.setattr("senior_exam_writer_lib.llama_cpp_client.llama_embed", fail_if_embedding_called)

    cmd_prepare_pipeline(
        argparse.Namespace(
            requirements="生成计算题。",
            requirements_file=None,
            input=[str(source_root)],
            output_dir=str(output_dir),
            db=str(db_path),
            task_name="quoted path test",
            language="zh-CN",
            writer_count=2,
            embed_url="http://127.0.0.1:8081",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    next_commands = (output_dir / "next_commands.ps1").read_text(encoding="utf-8")
    assert "--db '" in next_commands
    assert "exam db''s.sqlite" in next_commands
    assert "prepared output''s" in next_commands
    assert '\\"' not in next_commands
    assert '"TASK_NAME"' not in next_commands
