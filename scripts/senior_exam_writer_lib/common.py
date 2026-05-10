from __future__ import annotations

import datetime as dt
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".docx", ".pdf", ".epub", ".json", ".jsonl"}

DEFAULT_EMBED_URL = os.environ.get("LLAMA_CPP_EMBED_URL", "http://127.0.0.1:8081")

DEFAULT_LLM_URL = os.environ.get("LLAMA_CPP_LLM_URL", "http://127.0.0.1:8080")

DEFAULT_EMBED_MODEL = os.environ.get("LLAMA_CPP_EMBED_MODEL", "local-embedding")

DEFAULT_LLM_MODEL = os.environ.get("LLAMA_CPP_LLM_MODEL", "local-instruct")

DEFAULT_USER_AGENT = "senior-exam-writer/1.0 (+local evidence collection)"

@dataclass
class Section:
    title: str
    path: str
    text: str
    locator: str
    level: int = 1

@dataclass
class Evidence:
    id: str
    chunk_id: str
    source_id: str
    layer: str
    path: str
    title: str
    locator: str
    text: str
    score: float
    source_kind: str
    source_title: str
    source_path: str
    source_name: str | None
    source_url: str | None
    published_at: str | None

    def citation(self) -> str:
        source = self.source_title or Path(self.source_path).name
        path = f" - {self.path}" if self.path else ""
        locator = f" - {self.locator}" if self.locator else ""
        if self.source_url or self.published_at or self.source_name:
            parts = [p for p in [self.source_name or source, self.published_at, self.source_url or self.source_path, self.locator] if p]
            return " - ".join(parts)
        return f"{source}{path}{locator}"

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

def stable_id(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()[:24]
