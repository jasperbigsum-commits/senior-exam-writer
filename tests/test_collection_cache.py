from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from senior_exam_writer_lib.cli import cmd_collect_exam_sources
from senior_exam_writer_lib.collection import collect_exam_sources, collect_urls
from senior_exam_writer_lib.runtime import persist_fetch_cache
from senior_exam_writer_lib.store import ensure_db


def test_collect_exam_sources_collapses_duplicate_local_content(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    text = "Repeated historical exam passage."
    (source_dir / "a.txt").write_text(text, encoding="utf-8")
    (source_dir / "b.txt").write_text(text, encoding="utf-8")

    result = collect_exam_sources(
        urls=[],
        local_paths=[source_dir],
        out_dir=tmp_path / "downloads",
        jsonl_path=tmp_path / "collected.jsonl",
        source_name="seed corpus",
        tags=["historical_exam"],
        query="duplicate scan",
        timeout=5,
        user_agent="test-agent",
    )

    assert result["count"] == 1

    records = [
        json.loads(line)
        for line in (tmp_path / "collected.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["content_hash"]
    assert records[0]["raw_path"]


def test_collect_urls_normalizes_html_metadata(monkeypatch, tmp_path: Path) -> None:
    html = """
    <html>
      <head>
        <title>Archive Item</title>
        <meta property="article:published_time" content="2024-01-02" />
        <meta property="og:site_name" content="Archive Site" />
      </head>
      <body><p>Historical source body.</p></body>
    </html>
    """.encode("utf-8")

    monkeypatch.setattr(
        "senior_exam_writer_lib.collection.fetch_url",
        lambda url, timeout, user_agent: (html, "text/html; charset=utf-8", "https://example.com/archive-item"),
    )

    result = collect_urls(
        urls=["https://example.com/archive-item"],
        out_dir=tmp_path / "downloads",
        jsonl_path=tmp_path / "collected.jsonl",
        source_name=None,
        tags=["historical_exam"],
        query="html metadata",
        timeout=5,
        user_agent="test-agent",
    )

    record = result["records"][0]
    assert record["title"] == "Archive Item"
    assert record["date"] == "2024-01-02"
    assert record["source"] == "Archive Site"
    assert "published_at" not in record


def test_persist_fetch_cache_uses_record_whitelist_flags(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "cache.sqlite")
    try:
        ensure_db(conn)
        persist_fetch_cache(
            conn,
            [
                {
                    "url": "https://allowed.example.com/item",
                    "raw_path": str(tmp_path / "allowed.txt"),
                    "content_hash": "hash-1",
                    "retrieved_at": "2026-05-11T00:00:00+00:00",
                    "is_whitelisted": True,
                },
                {
                    "url": "https://blocked.example.com/item",
                    "raw_path": str(tmp_path / "blocked.txt"),
                    "content_hash": "hash-2",
                    "retrieved_at": "2026-05-11T00:00:00+00:00",
                    "is_whitelisted": False,
                },
            ],
            is_whitelisted=False,
        )
        rows = conn.execute(
            "SELECT url, metadata_json FROM fetch_cache ORDER BY url"
        ).fetchall()
    finally:
        conn.close()

    metadata_by_url = {row[0]: json.loads(row[1]) for row in rows}
    assert metadata_by_url["https://allowed.example.com/item"]["is_whitelisted"] is True
    assert metadata_by_url["https://blocked.example.com/item"]["is_whitelisted"] is False


def test_collect_exam_sources_cli_supports_input_alias_and_ingest(tmp_path: Path, capsys) -> None:
    source_dir = tmp_path / "historical"
    source_dir.mkdir()
    (source_dir / "exam.txt").write_text("Historical exam item for duplicate scan.", encoding="utf-8")
    db_path = tmp_path / "exam.sqlite"

    cmd_collect_exam_sources(
        type(
            "Args",
            (),
            {
                "db": str(db_path),
                "local_path": None,
                "input": [str(source_dir)],
                "url": None,
                "url_file": None,
                "whitelist_domain": None,
                "out_dir": str(tmp_path / "downloads"),
                "output_jsonl": str(tmp_path / "historical.jsonl"),
                "source_name": "local prior exams",
                "title": "Historical Exam Corpus",
                "published_at": None,
                "version": None,
                "tag": ["historical_exam"],
                "query": "prior exam scan",
                "timeout": 5,
                "user_agent": "test-agent",
                "ingest": True,
                "embed": False,
                "embed_url": "http://127.0.0.1:8081",
                "embed_model": "local-embedding",
                "max_chars": 900,
                "dedup_threshold": 0.9,
                "semantic_dedup_threshold": 0.985,
                "allow_duplicate_chunks": False,
            },
        )()
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["ingested"]["kind"] == "historical_exam"

    conn = sqlite3.connect(db_path)
    try:
        kind = conn.execute("SELECT kind FROM sources LIMIT 1").fetchone()[0]
    finally:
        conn.close()

    assert kind == "historical_exam"
