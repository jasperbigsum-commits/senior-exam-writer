from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .common import stable_id


CONNECTOR_RULES: dict[str, dict[str, str]] = {
    ".pdf": {
        "connector": "pdf_reader",
        "llamaindex_hint": "Use a PDF reader connector or SimpleDirectoryReader with a PDF file extractor.",
    },
    ".docx": {
        "connector": "docx_reader",
        "llamaindex_hint": "Use a DOCX reader connector or SimpleDirectoryReader with a DOCX file extractor.",
    },
    ".epub": {
        "connector": "epub_reader",
        "llamaindex_hint": "Use an EPUB reader connector or convert to structured text before indexing.",
    },
    ".md": {
        "connector": "markdown_reader",
        "llamaindex_hint": "Use a Markdown/text reader connector; preserve headings as metadata when possible.",
    },
    ".markdown": {
        "connector": "markdown_reader",
        "llamaindex_hint": "Use a Markdown/text reader connector; preserve headings as metadata when possible.",
    },
    ".txt": {
        "connector": "text_reader",
        "llamaindex_hint": "Use a plain text reader connector.",
    },
    ".json": {
        "connector": "json_reader",
        "llamaindex_hint": "Use a JSON reader connector and keep source fields as metadata.",
    },
    ".jsonl": {
        "connector": "jsonl_reader",
        "llamaindex_hint": "Use a JSONL reader connector and keep each record's source metadata.",
    },
}


def connector_for_path(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    rule = CONNECTOR_RULES.get(
        suffix,
        {
            "connector": "simple_directory_reader",
            "llamaindex_hint": "Use SimpleDirectoryReader or a custom reader for this file type.",
        },
    )
    return {"suffix": suffix, **rule}


def archive_original_sources(files: list[Path], roots: list[Path], archive_dir: Path) -> dict[str, dict[str, Any]]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    seen_targets: set[str] = set()
    records: dict[str, dict[str, Any]] = {}
    for path in files:
        source = path.expanduser().resolve()
        relative = _relative_archive_path(source, roots)
        target = archive_dir / relative
        key = str(target.resolve()).lower()
        if key in seen_targets:
            target = archive_dir / relative.parent / f"{source.stem}-{stable_id(str(source))[:8]}{source.suffix}"
        seen_targets.add(str(target.resolve()).lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records[str(source)] = {
            "archive_path": str(target.resolve()),
            "archive_relative_path": str(target.relative_to(archive_dir)),
            "connector_plan": connector_for_path(source),
        }
    return records


def _relative_archive_path(source: Path, roots: list[Path]) -> Path:
    for root in roots:
        resolved = root.expanduser().resolve()
        try:
            if resolved.is_dir():
                return source.relative_to(resolved)
            if resolved.is_file() and source == resolved:
                return Path(source.name)
        except ValueError:
            continue
    return Path(source.name)
