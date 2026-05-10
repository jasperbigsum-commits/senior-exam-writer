from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from urllib.parse import ParseResult, urlparse
from urllib.request import urlopen

from .common import now_iso, stable_id

LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


@dataclass(frozen=True)
class RuntimePaths:
    db: Path
    sidecar_root: Path
    runtime_dir: Path
    downloads_dir: Path
    reports_dir: Path

    def to_manifest(self) -> dict[str, object]:
        return {
            "paths": {
                "db": str(self.db),
                "sidecar_root": str(self.sidecar_root),
                "runtime_dir": str(self.runtime_dir),
                "downloads": str(self.downloads_dir),
                "reports": str(self.reports_dir),
            }
        }


def ensure_local_base_url(url: str) -> ParseResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError(f"url must target a local loopback endpoint: {url}")
    return parsed


def init_runtime_layout(db_path: str | Path, sidecar_root: str | Path | None = None) -> dict[str, object]:
    db = Path(db_path).resolve()
    root = Path(sidecar_root).resolve() if sidecar_root is not None else db.parent
    runtime_dir = root / ".senior-exam-writer" / db.stem
    downloads_dir = runtime_dir / "downloads"
    reports_dir = runtime_dir / "reports"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths = RuntimePaths(
        db=db,
        sidecar_root=root,
        runtime_dir=runtime_dir,
        downloads_dir=downloads_dir,
        reports_dir=reports_dir,
    )
    return paths.to_manifest()


def probe_json(url: str, timeout: int = 10) -> dict[str, object]:
    ensure_local_base_url(url)
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            data = json.loads(payload) if payload else None
            return {
                "ok": True,
                "url": url,
                "status": getattr(response, "status", None),
                "json": data,
            }
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": str(exc),
        }


def persist_fetch_cache(
    conn: sqlite3.Connection,
    records: list[dict[str, object]],
    is_whitelisted: bool,
) -> None:
    for record in records:
        cache_url = str(record.get("url") or record.get("raw_path") or "")
        content_hash = str(record.get("content_hash") or "")
        cache_key = stable_id(cache_url, content_hash)
        metadata = {
            "title": record.get("title"),
            "source": record.get("source"),
            "tags": record.get("tags") or [],
            "retrieval_query": record.get("retrieval_query"),
            "content_hash": content_hash,
            "is_whitelisted": bool(record.get("is_whitelisted", is_whitelisted)),
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO fetch_cache
            (cache_key, url, response_status, response_headers_json, response_body_path, metadata_json, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                cache_url,
                200 if record.get("url") else None,
                json.dumps({}, ensure_ascii=False),
                str(record.get("raw_path") or ""),
                json.dumps(metadata, ensure_ascii=False),
                str(record.get("retrieved_at") or now_iso()),
                None,
            ),
        )
    conn.commit()
