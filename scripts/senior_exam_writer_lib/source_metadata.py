from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
        return records
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def current_affairs_metadata_issues(
    *,
    input_path: Path,
    source_name: str | None,
    url: str | None,
    published_at: str | None,
) -> list[str]:
    records = read_json_records(input_path) if input_path.is_file() else []
    issues: list[str] = []
    if records:
        for idx, record in enumerate(records, 1):
            has_source = bool(record.get("source") or record.get("source_name") or source_name)
            has_date = bool(record.get("date") or record.get("published_at") or record.get("publish_date") or published_at)
            has_locator = bool(record.get("url") or record.get("raw_path") or url)
            if not has_source:
                issues.append(f"current_affairs record {idx} is missing source/source_name")
            if not has_date:
                issues.append(f"current_affairs record {idx} is missing date/published_at")
            if not has_locator:
                issues.append(f"current_affairs record {idx} is missing url/raw_path")
        return issues

    if not source_name:
        issues.append("current_affairs ingestion requires --source-name when records do not provide source")
    if not published_at:
        issues.append("current_affairs ingestion requires --published-at when records do not provide date")
    if not url and input_path.suffix.lower() not in {".json", ".jsonl"}:
        issues.append("current_affairs ingestion requires --url for non-JSON source files")
    return issues
