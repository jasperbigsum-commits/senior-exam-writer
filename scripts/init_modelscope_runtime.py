#!/usr/bin/env python3
"""Prepare ModelScope-first local embedding commands for senior-exam-writer.

The script intentionally does not start long-running llama.cpp servers. It
downloads or locates the local embedding model and prints the command that must
keep running before the evidence pipeline can ingest, retrieve, or review.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from senior_exam_writer_lib.local_embedding_runtime import (
    DEFAULT_CACHE_DIR,
    DEFAULT_EMBED_REPO,
    build_embedding_command,
    resolve_embedding_model,
    resolve_llama_server,
)



def configure_stdio_utf8() -> None:
    """Keep Chinese JSON output stable on Windows terminals and subprocess captures."""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def quote_arg(text: str) -> str:
    return f'"{text}"' if " " in text else text


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Prepare ModelScope local llama.cpp runtime commands.")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--embed-repo", default=DEFAULT_EMBED_REPO)
    parser.add_argument("--embed-model-path")
    parser.add_argument("--prefer-embed-file", default="Q8_0")
    parser.add_argument("--llama-server", default=os.environ.get("LLAMA_SERVER", "llama-server"))
    parser.add_argument("--embed-port", type=int, default=8081)
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        embed_model, embed_meta = resolve_embedding_model(
            repo_id=args.embed_repo,
            cache_dir=cache_dir,
            explicit_path=args.embed_model_path,
            prefer_file=args.prefer_embed_file,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if not embed_model:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "could not locate required embedding GGUF file",
                    "embed": embed_meta,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    server_hint = resolve_llama_server(args.llama_server)
    embed_cmd = " ".join(quote_arg(part) for part in build_embedding_command(server_hint, embed_model, args.embed_port))
    payload = {
        "ok": True,
        "source": "ModelScope",
        "runner": "Use uv run for Python commands in this skill.",
        "embedding": {
            "repo": args.embed_repo,
            "model_path": str(embed_model),
            "command": embed_cmd,
            "url": f"http://127.0.0.1:{args.embed_port}",
        },
        "generation": "not required; Codex/agent performs generation and review from retrieved evidence. Use a local LLM only as an optional offline verifier.",
        "next_check": (
            "uv run python scripts/senior_exam_writer.py init-runtime "
            f"--db ./exam_evidence.sqlite --embed-url http://127.0.0.1:{args.embed_port}"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
