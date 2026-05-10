from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any

from .common import DEFAULT_USER_AGENT, SUPPORTED_SUFFIXES, now_iso
from .parsing import html_to_text, load_document, normalize_ws

def first_match(patterns: list[str], text: str, flags: int = re.I | re.S) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = unescape(match.group(1)).strip()
            value = re.sub(r"\s+", " ", value)
            if value:
                return value
    return None

def extract_html_metadata(raw: str, url: str) -> dict[str, str | None]:
    title = first_match(
        [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']title["\'][^>]+content=["\']([^"\']+)["\']',
            r"<title[^>]*>(.*?)</title>",
        ],
        raw,
    )
    published_at = first_match(
        [
            r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']publishdate["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
            r'"datePublished"\s*:\s*"([^"]+)"',
        ],
        raw,
    )
    source = first_match(
        [
            r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']source["\'][^>]+content=["\']([^"\']+)["\']',
            r'"publisher"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"',
        ],
        raw,
    )
    domain = urllib.parse.urlparse(url).netloc
    return {"title": title, "published_at": published_at, "source": source or domain}

def guess_extension(url: str, content_type: str | None) -> str:
    path_suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if path_suffix in SUPPORTED_SUFFIXES or path_suffix in {".html", ".htm"}:
        return ".txt" if path_suffix in {".html", ".htm"} else path_suffix
    ctype = (content_type or "").lower()
    if "pdf" in ctype:
        return ".pdf"
    if "officedocument.wordprocessingml.document" in ctype or "msword" in ctype:
        return ".docx"
    if "json" in ctype:
        return ".json"
    if "html" in ctype:
        return ".txt"
    return ".txt"

def safe_download_name(url: str, content_type: str | None) -> str:
    parsed = urllib.parse.urlparse(url)
    domain = re.sub(r"[^A-Za-z0-9._-]+", "-", parsed.netloc).strip("-") or "source"
    stem = Path(parsed.path).stem or "index"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")[:80] or "item"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{domain}-{stem}-{digest}{guess_extension(url, content_type)}"

def fetch_url(url: str, timeout: int, user_agent: str) -> tuple[bytes, str | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            content_type = resp.headers.get("Content-Type")
            final_url = resp.geturl()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} while downloading {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot download {url}: {exc}") from exc
    return payload, content_type, final_url

def text_from_download(path: Path, raw: bytes, content_type: str | None) -> tuple[str, dict[str, Any]]:
    ctype = (content_type or "").lower()
    try:
        if path.suffix.lower() in {".docx", ".pdf", ".epub"}:
            parts = load_document(path)
            return normalize_ws("\n".join(text for _, text in parts)), {}
        decoded = raw.decode("utf-8", errors="replace")
        if "html" in ctype or re.search(r"<html|<!doctype html", decoded[:1000], re.I):
            return html_to_text(decoded), extract_html_metadata(decoded, "")
        if path.suffix.lower() in {".json", ".jsonl"}:
            return decoded, {}
        return normalize_ws(decoded), {}
    except Exception as exc:
        return "", {"extraction_error": str(exc)}

def read_url_list(urls: list[str] | None, url_file: str | None) -> list[str]:
    collected: list[str] = []
    for url in urls or []:
        if url.strip():
            collected.append(url.strip())
    if url_file:
        for line in Path(url_file).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                collected.append(line)
    seen: set[str] = set()
    unique = []
    for url in collected:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique

def collect_urls(
    *,
    urls: list[str],
    out_dir: Path,
    jsonl_path: Path,
    source_name: str | None,
    tags: list[str],
    query: str | None,
    timeout: int,
    user_agent: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for url in urls:
        raw, content_type, final_url = fetch_url(url, timeout=timeout, user_agent=user_agent)
        raw_name = safe_download_name(final_url, content_type)
        raw_path = out_dir / raw_name
        raw_path.write_bytes(raw)
        extracted_text, extra_meta = text_from_download(raw_path, raw, content_type)
        html_meta = {}
        if raw_path.suffix == ".txt":
            decoded = raw.decode("utf-8", errors="replace")
            if "html" in (content_type or "").lower() or re.search(r"<html|<!doctype html", decoded[:1000], re.I):
                html_meta = extract_html_metadata(decoded, final_url)
        domain = urllib.parse.urlparse(final_url).netloc
        title = html_meta.get("title") or Path(urllib.parse.urlparse(final_url).path).stem or domain
        published_at = html_meta.get("published_at")
        source = source_name or html_meta.get("source") or domain
        record = {
            "title": title,
            "date": published_at,
            "source": source,
            "url": final_url,
            "tags": tags,
            "retrieval_query": query,
            "retrieved_at": now_iso(),
            "raw_path": str(raw_path.resolve()),
            "content_type": content_type,
            "full_text": extracted_text,
        }
        record.update(extra_meta)
        records.append(record)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"count": len(records), "jsonl": str(jsonl_path.resolve()), "records": records}
