#!/usr/bin/env python3
"""One-command batch runner that hides temporary llama.cpp service management."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from senior_exam_writer_lib.common import configure_stdio_utf8
from senior_exam_writer_lib.ingest import collect_files
from senior_exam_writer_lib.local_embedding_runtime import (
    DEFAULT_CACHE_DIR,
    DEFAULT_EMBED_REPO,
    build_embedding_command,
    find_free_port,
    launch_embedding_server,
    resolve_embedding_model,
    resolve_llama_server,
    stop_process,
    wait_for_embedding_ready,
)
from senior_exam_writer_lib.prepare_pipeline import build_prepare_pipeline


def run_cmd(args: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, encoding="utf-8", errors="replace")
    return {
        "command": " ".join(args),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def python_command(*parts: str) -> list[str]:
    return [sys.executable, *parts]


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Run a simplified senior-exam-writer batch pipeline.")
    parser.add_argument("--requirements", help="natural-language requirement text")
    parser.add_argument("--requirements-file", help="file containing natural-language requirement text")
    parser.add_argument("--input", action="append", required=True, help="material file or directory; repeatable")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--task-name")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--writer-count", type=int, default=3)
    parser.add_argument("--prepare-only", action="store_true", help="do not start embedding service or ingest")
    parser.add_argument("--ingest-kind", default="book")
    parser.add_argument("--embed-model-path")
    parser.add_argument("--embed-repo", default=DEFAULT_EMBED_REPO)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--prefer-embed-file", default="Q8_0")
    parser.add_argument("--llama-server", default="llama-server")
    parser.add_argument("--port", type=int, help="embedding port; omitted means auto-pick an available port")
    parser.add_argument("--keep-server", action="store_true", help="leave the temporary embedding server running")
    parser.add_argument("--startup-timeout", type=int, default=120)
    parser.add_argument("--max-workers", type=int, default=4, help="parallel workers for file inspection")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir)
    if args.requirements_file:
        requirement_text = Path(args.requirements_file).read_text(encoding="utf-8", errors="replace")
    else:
        requirement_text = args.requirements or ""
    material_paths = [Path(path) for path in args.input]
    port = args.port or find_free_port()
    embed_url = f"http://127.0.0.1:{port}"

    prepare_report = build_prepare_pipeline(
        requirement_text=requirement_text,
        materials=material_paths,
        output_dir=output_dir,
        db_path=args.db,
        task_name=args.task_name,
        language=args.language,
        writer_count=args.writer_count,
        embed_url=embed_url,
    )
    result: dict[str, Any] = {
        "ok": True,
        "mode": "prepare_only" if args.prepare_only else "managed_embedding_batch",
        "prepare": {
            "output_dir": prepare_report["output_dir"],
            "source_count": len(prepare_report["source_manifest"]),
            "prompt_package": str((output_dir / "prompt_package.json").resolve()),
        },
        "embed_url": embed_url,
        "steps": [],
    }
    if args.prepare_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    process = None
    exit_code = 0
    try:
        model_path, model_meta = resolve_embedding_model(
            repo_id=args.embed_repo,
            cache_dir=Path(args.cache_dir).expanduser().resolve(),
            explicit_path=args.embed_model_path,
            prefer_file=args.prefer_embed_file,
        )
        if not model_path:
            raise RuntimeError(f"could not locate embedding model: {model_meta}")
        llama_server = resolve_llama_server(args.llama_server)
        command = build_embedding_command(llama_server, model_path, port)
        log_path = output_dir / "managed_embedding_server.log"
        process = launch_embedding_server(command, log_path)
        probe = wait_for_embedding_ready(
            base_url=embed_url,
            embed_model="local-embedding",
            process=process,
            timeout_seconds=args.startup_timeout,
        )
        result["embedding"] = {
            "model_path": str(model_path),
            "command": command,
            "probe": probe,
            "log_path": str(log_path.resolve()),
        }

        init_db = run_cmd(python_command("scripts/senior_exam_writer.py", "init-db", "--db", args.db), cwd=root)
        result["steps"].append(init_db)
        if init_db["returncode"] != 0:
            raise RuntimeError("init-db failed")

        files = _collect_batch_files(material_paths, max_workers=max(1, args.max_workers))
        ingest_steps = []
        for file_path in files:
            step = run_cmd(
                [
                    *python_command(
                    "scripts/senior_exam_writer.py",
                    "ingest",
                    "--db",
                    args.db,
                    "--input",
                    str(file_path),
                    "--kind",
                    args.ingest_kind,
                    "--embed",
                    "--embed-url",
                    embed_url,
                    ),
                ],
                cwd=root,
            )
            ingest_steps.append(step)
            if step["returncode"] != 0:
                raise RuntimeError(f"ingest failed: {file_path}")
        result["steps"].extend(ingest_steps)

        audit = run_cmd(python_command("scripts/senior_exam_writer.py", "audit-duplicates", "--db", args.db, "--backfill"), cwd=root)
        result["steps"].append(audit)
        if audit["returncode"] != 0:
            raise RuntimeError("audit-duplicates failed")
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        exit_code = 1
    finally:
        if process is not None and not args.keep_server:
            try:
                stop_process(process)
                result["server_stopped"] = True
            except Exception as exc:
                result["server_stopped"] = False
                result["server_stop_error"] = str(exc)
                result["ok"] = False
                result["error"] = result.get("error") or "failed to stop temporary embedding server"
                exit_code = 1

    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output, file=sys.stderr if exit_code else sys.stdout)
    return exit_code


def _collect_batch_files(material_paths: list[Path], *, max_workers: int) -> list[Path]:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        groups = list(executor.map(collect_files, material_paths))
    files: list[Path] = []
    seen: set[str] = set()
    for group in groups:
        for path in group:
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                files.append(path)
    return sorted(files, key=lambda path: str(path).lower())


if __name__ == "__main__":
    raise SystemExit(main())
