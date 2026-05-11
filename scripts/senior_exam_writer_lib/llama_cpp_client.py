from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .common import DEFAULT_EMBED_MODEL, DEFAULT_LLM_MODEL

def http_json(url: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc}") from exc
    return json.loads(raw)

def llama_embed(texts: list[str], base_url: str, model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    base = base_url.rstrip("/")
    payload = {"model": model, "input": texts}
    try:
        data = http_json(f"{base}/v1/embeddings", payload, timeout=180)
        embeddings = data.get("data", [])
        return [list(map(float, item["embedding"])) for item in embeddings]
    except Exception as first_error:
        if len(texts) != 1:
            vectors = []
            for text in texts:
                vectors.extend(llama_embed([text], base_url, model))
            return vectors
        fallback_payload = {"content": texts[0]}
        try:
            data = http_json(f"{base}/embedding", fallback_payload, timeout=180)
        except Exception as second_error:
            raise RuntimeError(f"embedding failed: {first_error}; fallback failed: {second_error}") from second_error
        emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if not emb:
            raise RuntimeError(f"embedding response did not include a vector: {data}")
        return [list(map(float, emb))]

def llama_chat(
    messages: list[dict[str, str]],
    base_url: str,
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    base = base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    prompt = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in messages)
    first_error: Exception | None = None
    try:
        data = http_json(f"{base}/v1/chat/completions", payload, timeout=300)
        content = data["choices"][0]["message"].get("content") or ""
        if content.strip():
            return content
        first_error = RuntimeError("chat completion returned empty content")
    except Exception as exc:
        first_error = exc
    fallback_payload = {
        "prompt": prompt,
        "temperature": temperature,
        "n_predict": max_tokens,
        "stream": False,
    }
    try:
        data = http_json(f"{base}/completion", fallback_payload, timeout=300)
    except Exception as second_error:
        first_message = first_error or "chat completion was not attempted"
        raise RuntimeError(f"generation failed: {first_message}; fallback failed: {second_error}") from second_error
    return data.get("content", "")
