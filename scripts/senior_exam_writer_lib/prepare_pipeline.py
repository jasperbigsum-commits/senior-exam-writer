from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import SUPPORTED_SUFFIXES, now_iso
from .ingest import collect_files
from .parsing import load_document, sections_from_parts
from .requirement_prompts import build_requirement_prompt_package
from .source_archive import archive_original_sources, connector_for_path


def build_prepare_pipeline(
    *,
    requirement_text: str,
    materials: list[Path],
    output_dir: Path,
    db_path: str,
    task_name: str | None = None,
    language: str = "zh-CN",
    writer_count: int = 3,
    embed_url: str = "http://127.0.0.1:8081",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    package = build_requirement_prompt_package(
        requirement_text,
        task_name=task_name,
        language=language,
        writer_count=writer_count,
    )
    discovered_files = _discover_files(materials)
    archive_records = archive_original_sources(discovered_files, materials, output_dir / "original_sources")
    source_manifest = [_inspect_source(path, archive_records.get(str(path.resolve()), {})) for path in discovered_files]
    summary = {
        "ok": True,
        "mode": "prepare_only_no_embedding",
        "created_at": now_iso(),
        "db": db_path,
        "output_dir": str(output_dir.resolve()),
        "entry_requirement": package["entry_requirement"],
        "prompt_package": package,
        "source_manifest": source_manifest,
        "next_commands": _next_commands(db_path, output_dir, embed_url),
        "blocked_until_embedding_ready": [
            "ingest --embed",
            "plan-evidence",
            "retrieve",
            "generate-candidates",
            "audit-question-similarity",
            "complete-task",
        ],
        "policy": [
            "This mode performs deterministic batching only; it does not create evidence, vectors, similarity scores, or approved questions.",
            "Start the local embedding server and rerun the evidence-stage commands before using any source as citation support.",
            "Original files are archived under original_sources with relative directory structure and connector hints for LlamaIndex or local ingestion.",
        ],
    }
    _write_json(output_dir / "prompt_package.json", package)
    _write_jsonl(output_dir / "prompt_stages.jsonl", package.get("stages") or [])
    _write_json(output_dir / "source_manifest.json", source_manifest)
    _write_task_templates(output_dir, package, source_manifest)
    _write_json(output_dir / "prepare_report.json", summary)
    _write_text(output_dir / "next_commands.ps1", "\n".join(summary["next_commands"]) + "\n")
    return summary


def _discover_files(materials: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for material in materials:
        for path in collect_files(material):
            key = str(path.resolve())
            if key not in seen and path.suffix.lower() in SUPPORTED_SUFFIXES:
                seen.add(key)
                files.append(path)
    return sorted(files, key=lambda path: str(path).lower())


def _inspect_source(path: Path, archive_record: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path.resolve()),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "status": "ok",
        "connector_plan": connector_for_path(path),
    }
    if archive_record:
        record.update(
            {
                "archive_path": archive_record.get("archive_path"),
                "archive_relative_path": archive_record.get("archive_relative_path"),
                "connector_plan": archive_record.get("connector_plan") or record["connector_plan"],
            }
        )
    try:
        parts = load_document(path)
        sections, toc_titles = sections_from_parts(parts, path.stem)
    except Exception as exc:
        record.update({"status": "parse_failed", "error": str(exc)})
        return record
    chars = sum(len(text or "") for _locator, text in parts)
    record.update(
        {
            "parts": len(parts),
            "sections": len(sections),
            "toc_items": len(toc_titles),
            "chars": chars,
            "sample_paths": [section.path for section in sections[:5]],
        }
    )
    return record


def _next_commands(db_path: str, output_dir: Path, embed_url: str) -> list[str]:
    output = str(output_dir)
    db = _quote_pwsh_arg(db_path)
    embed = _quote_pwsh_arg(embed_url)
    return [
        f"uv run python scripts/senior_exam_writer.py init-db --db {db}",
        f"uv run python scripts/senior_exam_writer.py init-runtime --db {db} --embed-url {embed}",
        f"uv run python scripts/senior_exam_writer.py create-task --db {db} --name {_quote_pwsh_arg('TASK_NAME')} --outline {_quote_pwsh_arg(str(Path(output) / 'outline.json'))} --source-policy {_quote_pwsh_arg(str(Path(output) / 'source_policy.json'))} --question-rules {_quote_pwsh_arg(str(Path(output) / 'question_rules.json'))} --requirements {_quote_pwsh_arg(str(Path(output) / 'requirements.json'))} --coverage {_quote_pwsh_arg(str(Path(output) / 'coverage.json'))}",
        f"uv run python scripts/senior_exam_writer.py ingest --db {db} --input {_quote_pwsh_arg('MATERIAL_PATH')} --kind book --embed --embed-url {embed}",
        f"uv run python scripts/senior_exam_writer.py audit-duplicates --db {db} --backfill",
        f"uv run python scripts/senior_exam_writer.py plan-knowledge --db {db} --task-id {_quote_pwsh_arg('TASK_ID')}",
        f"uv run python scripts/senior_exam_writer.py plan-evidence --db {db} --task-id {_quote_pwsh_arg('TASK_ID')} --embed-url {embed}",
        f"uv run python scripts/senior_exam_writer.py generate-candidates --db {db} --planning-unit-id {_quote_pwsh_arg('PLANNING_UNIT_ID')} --topic {_quote_pwsh_arg('TOPIC')} --writer-count 3 --embed-url {embed}",
        f"uv run python scripts/senior_exam_writer.py audit-question-similarity --db {db} --planning-unit-id {_quote_pwsh_arg('PLANNING_UNIT_ID')} --task-id {_quote_pwsh_arg('TASK_ID')} --embed-url {embed}",
    ]


def _quote_pwsh_arg(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_task_templates(output_dir: Path, package: dict[str, Any], source_manifest: list[dict[str, Any]]) -> None:
    task_name = str(package.get("task_name") or "exam task")
    hints = package.get("hints") if isinstance(package.get("hints"), dict) else {}
    question_type = str(hints.get("question_type") or "short_answer")
    difficulty = str(hints.get("difficulty") or "medium")
    source_paths = [record.get("path") for record in source_manifest if record.get("status") == "ok"]
    templates = {
        "outline.json": {
            "exam_name": task_name,
            "topics": [task_name],
            "modules": [{"name": task_name, "objectives": ["依据材料完成命题"]}],
        },
        "source_policy.json": {
            "required_core_kinds": ["book"],
            "required_spec_kinds": [],
            "allowed_background_kinds": ["current_affairs"],
            "current_affairs_requires_url_and_date": True,
            "question_bank_usage": "style_only_no_copying",
            "prepared_source_paths": source_paths,
        },
        "question_rules.json": {
            "question_types": sorted({question_type, "short_answer"}),
            "require_citations": True,
            "avoid_duplicate_knowledge_points": True,
        },
        "requirements.json": {
            "review_required": True,
            "entry_requirement": package.get("entry_requirement", ""),
            "prepare_only": True,
            "must_run_embedding_stage_before_citation_use": True,
        },
        "coverage.json": {
            "total_items": 1,
            "distribution": [
                {
                    "target": task_name,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "count": 1,
                }
            ],
            "avoid_repeating_knowledge_points": True,
        },
    }
    for filename, payload in templates.items():
        _write_json(output_dir / filename, payload)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
