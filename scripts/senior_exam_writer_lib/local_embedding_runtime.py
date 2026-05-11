from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any

from .llama_cpp_client import llama_embed

DEFAULT_EMBED_REPO = "Qwen/Qwen3-Embedding-0.6B-GGUF"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "modelscope" / "senior-exam-writer"


def find_gguf(root: Path, prefer: str | None = None) -> Path | None:
    files = sorted(root.rglob("*.gguf"), key=lambda path: path.stat().st_size if path.exists() else 0, reverse=True)
    if prefer:
        lowered = prefer.lower()
        for path in files:
            if lowered in path.name.lower():
                return path
    return files[0] if files else None


def snapshot_download(repo_id: str, cache_dir: Path, prefer_file: str | None = None) -> Path:
    try:
        from modelscope import snapshot_download as ms_snapshot_download  # type: ignore
    except Exception as exc:
        raise RuntimeError("modelscope package is required. Run this skill with uv: uv run python ...") from exc
    allow_pattern = f"*{prefer_file}*.gguf" if prefer_file else "*.gguf"
    return Path(ms_snapshot_download(repo_id, cache_dir=str(cache_dir), allow_file_pattern=allow_pattern))


def resolve_embedding_model(
    *,
    repo_id: str,
    cache_dir: Path,
    explicit_path: str | None,
    prefer_file: str | None,
) -> tuple[Path | None, dict[str, Any]]:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".gguf":
            return path, {"mode": "explicit_file", "path": str(path)}
        if path.is_dir():
            gguf = find_gguf(path, prefer_file)
            return gguf, {"mode": "explicit_dir", "path": str(path)}
        return None, {"mode": "explicit_missing", "path": str(path)}
    repo_root = snapshot_download(repo_id, cache_dir, prefer_file)
    gguf = find_gguf(repo_root, prefer_file)
    return gguf, {"mode": "modelscope", "repo_id": repo_id, "repo_root": str(repo_root)}


def resolve_llama_server(name_or_path: str) -> str:
    resolved = shutil.which(name_or_path)
    if resolved:
        return resolved
    path = Path(name_or_path).expanduser()
    if path.exists():
        return str(path.resolve())
    raise RuntimeError(f"llama-server not found: {name_or_path}")


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def build_embedding_command(llama_server: str, model_path: Path, port: int) -> list[str]:
    return [
        llama_server,
        "-m",
        str(model_path),
        "--embedding",
        "--pooling",
        "last",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def launch_embedding_server(command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    kwargs: dict[str, Any] = {
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(command, **kwargs)


def wait_for_embedding_ready(
    *,
    base_url: str,
    embed_model: str,
    process: subprocess.Popen[bytes] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"llama-server exited early with code {process.returncode}; last_error={last_error}")
        try:
            vectors = llama_embed(["中文向量健康检查：批量流程、证据入库、重复审查。"], base_url, embed_model)
            dimension = len(vectors[0]) if vectors and vectors[0] else 0
            if dimension > 0:
                return {"ok": True, "url": base_url, "model": embed_model, "dimension": dimension}
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"embedding server did not become ready within {timeout_seconds}s: {last_error}")


def stop_process(process: subprocess.Popen[bytes], timeout_seconds: int = 10) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)
