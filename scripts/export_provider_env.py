#!/usr/bin/env python3
"""Print OpenAI-compatible environment variables from Codex provider config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore


def _quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_posix(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def load_codex_config(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def build_env(config: dict, *, provider: str | None, api_key: str | None, model: str | None) -> dict[str, str]:
    provider_name = provider or str(config.get("model_provider") or "")
    providers = config.get("model_providers") or {}
    provider_config = providers.get(provider_name) or {}
    base_url = provider_config.get("base_url")
    if not base_url:
        raise ValueError(f"provider has no base_url: {provider_name}")
    return {
        "OPENAI_BASE_URL": str(base_url).rstrip("/"),
        "OPENAI_API_BASE": str(base_url).rstrip("/"),
        "OPENAI_API_KEY": api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_PROVIDER_API_KEY") or "local-provider-key",
        "OPENAI_MODEL": model or str(config.get("model") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export OpenAI-compatible env vars from Codex provider config.")
    parser.add_argument("--config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--provider", help="provider key under [model_providers]; default uses model_provider")
    parser.add_argument("--api-key", help="explicit API key for third-party OpenAI-compatible tools")
    parser.add_argument("--model", help="override model name exported as OPENAI_MODEL")
    parser.add_argument("--format", choices=["powershell", "posix", "json"], default="powershell")
    args = parser.parse_args(argv)

    env = build_env(load_codex_config(Path(args.config).expanduser()), provider=args.provider, api_key=args.api_key, model=args.model)
    if args.format == "json":
        print(json.dumps(env, ensure_ascii=False, indent=2))
    elif args.format == "posix":
        for key, value in env.items():
            print(f"export {key}={_quote_posix(value)}")
    else:
        for key, value in env.items():
            print(f"$env:{key} = {_quote_powershell(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
