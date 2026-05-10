from __future__ import annotations

import argparse
import json

import pytest

from senior_exam_writer_lib.cli import cmd_split_requirements
from senior_exam_writer_lib.requirement_prompts import (
    PROMPT_STAGE_ORDER,
    build_requirement_prompt_package,
    prompt_package_to_jsonl,
)


def test_requirement_prompt_package_splits_entry_need_into_stage_prompts() -> None:
    package = build_requirement_prompt_package(
        "请围绕共同富裕出3道中等难度单选题，必须先审查历届真题重复率。",
        task_name="共同富裕期末题",
        writer_count=2,
    )

    assert [stage["stage"] for stage in package["stages"]] == PROMPT_STAGE_ORDER
    assert package["hints"]["question_type"] == "single_choice"
    assert package["hints"]["difficulty"] == "medium"
    assert package["hints"]["count"] == "3"
    assert package["stages"][2]["parallelizable"] is True
    assert "audit-question-similarity" in package["stages"][6]["prompt"]
    assert package["stages"][4]["expected_output"]["writer_count"] == 2


def test_requirement_prompt_package_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="requirement text is required"):
        build_requirement_prompt_package("")


def test_prompt_package_jsonl_has_one_stage_per_line() -> None:
    package = build_requirement_prompt_package("生成2道简答题，要求证据充分。")
    lines = prompt_package_to_jsonl(package).strip().splitlines()

    assert len(lines) == len(PROMPT_STAGE_ORDER)
    assert json.loads(lines[0])["stage"] == "task_definition"


def test_cli_split_requirements_writes_json_and_jsonl(tmp_path, capsys) -> None:
    json_path = tmp_path / "prompts.json"
    jsonl_path = tmp_path / "prompts.jsonl"

    cmd_split_requirements(
        argparse.Namespace(
            requirements="生成4道材料分析题，要求多出题人闭环审核。",
            requirements_file=None,
            task_name="材料分析题任务",
            language="zh-CN",
            writer_count=3,
            output_json=str(json_path),
            output_jsonl=str(jsonl_path),
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert json_path.exists()
    assert jsonl_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["task_name"] == "材料分析题任务"
    assert len(jsonl_path.read_text(encoding="utf-8").strip().splitlines()) == len(PROMPT_STAGE_ORDER)
