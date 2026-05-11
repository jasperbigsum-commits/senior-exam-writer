#!/usr/bin/env python3
"""Optional wrapper for LlamaIndex RAG CLI with explicit provider env."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from export_provider_env import build_env, load_codex_config
from senior_exam_writer_lib.common import configure_stdio_utf8


def _merge_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    config = load_codex_config(Path(args.codex_config).expanduser())
    env.update(build_env(config, provider=args.provider, api_key=args.api_key, model=args.llm_model))
    if args.embed_base_url:
        env["SENIOR_EXAM_EMBED_BASE_URL"] = args.embed_base_url.rstrip("/")
    if args.embed_model:
        env["SENIOR_EXAM_EMBED_MODEL"] = args.embed_model
    if args.vector_db:
        env["SENIOR_EXAM_VECTOR_DB"] = args.vector_db
    return env


def _command(args: argparse.Namespace) -> list[str]:
    executable = shutil.which(args.executable)
    if executable is None:
        explicit = Path(args.executable).expanduser()
        if explicit.exists():
            executable = str(explicit.resolve())
    if executable is None:
        raise FileNotFoundError(
            f"LlamaIndex CLI executable not found: {args.executable}. "
            "Install a CLI that provides `llamaindex-cli`, or pass --executable C:/path/to/llamaindex-cli."
        )
    command = [executable, "rag"]
    if args.files:
        command.extend(args.files)
    if args.question:
        command.extend(["--question", args.question])
    if args.extra_args:
        command.extend(args.extra_args)
    return command


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_path = Path(args.output_json).expanduser() if args.output_json else None
    try:
        command = _command(args)
    except Exception as exc:
        payload = {
            "ok": False,
            "returncode": 127,
            "command": [args.executable, "rag"],
            "stdout": "",
            "stderr": str(exc),
            "backend": "llamaindex-cli",
            "notes": [
                "optional backend unavailable; use local SQLite vector retrieval or install/pass a LlamaIndex CLI executable",
                "provider/base_url was not used because the executable was missing",
            ],
        }
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    completed = subprocess.run(
        command,
        cwd=str(Path(args.cwd).expanduser().resolve()) if args.cwd else None,
        env=_merge_env(args),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "backend": "llamaindex-cli",
        "notes": [
            "optional backend; store or ingest returned evidence before using it in approved questions",
            "provider/base_url came from Codex config or explicit overrides",
        ],
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Run optional LlamaIndex RAG CLI with explicit provider/base_url env.")
    parser.add_argument("--files", action="append", help="file or directory passed to llamaindex-cli rag; repeatable")
    parser.add_argument("--question", help="query/question passed to llamaindex-cli rag")
    parser.add_argument("--output-json", help="write raw CLI result to a reusable local JSON file")
    parser.add_argument("--codex-config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--provider", help="provider key under [model_providers]; default uses Codex model_provider")
    parser.add_argument("--api-key", help="explicit API key for OpenAI-compatible provider")
    parser.add_argument("--llm-model", help="LLM model name exported as OPENAI_MODEL")
    parser.add_argument("--embed-base-url", help="explicit embedding provider base_url for custom RagCLI code")
    parser.add_argument("--embed-model", help="explicit embedding model for custom RagCLI code")
    parser.add_argument("--vector-db", help="vector database setting for custom RagCLI code")
    parser.add_argument("--executable", default="llamaindex-cli")
    parser.add_argument("--cwd")
    parser.add_argument("extra_args", nargs=argparse.REMAINDER, help="extra args after -- are forwarded to llamaindex-cli")
    args = parser.parse_args(argv)

    if args.extra_args and args.extra_args[0] == "--":
        args.extra_args = args.extra_args[1:]
    payload = run(args)
    stream = sys.stdout if payload["ok"] else sys.stderr
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)
    return 0 if payload["ok"] else int(payload["returncode"] or 1)


if __name__ == "__main__":
    raise SystemExit(main())
