from __future__ import annotations

import json
import subprocess

from export_provider_env import build_env
import llamaindex_rag


def test_export_provider_env_uses_codex_provider_base_url() -> None:
    config = {
        "model_provider": "custom",
        "model": "gpt-5.5",
        "model_providers": {
            "custom": {
                "base_url": "https://example.test/v1/",
            }
        },
    }

    env = build_env(config, provider=None, api_key="test-key", model=None)

    assert env["OPENAI_BASE_URL"] == "https://example.test/v1"
    assert env["OPENAI_API_BASE"] == "https://example.test/v1"
    assert env["OPENAI_API_KEY"] == "test-key"
    assert env["OPENAI_MODEL"] == "gpt-5.5"


def test_llamaindex_wrapper_injects_provider_env_and_caches_output(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
model_provider = "custom"
model = "gpt-test"

[model_providers.custom]
base_url = "https://provider.example/v1"
""".strip(),
        encoding="utf-8",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]

        class Completed:
            returncode = 0
            stdout = "中文结果"
            stderr = ""

        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("llamaindex_rag.shutil.which", lambda value: value)

    code = llamaindex_rag.main(
        [
            "--codex-config",
            str(config),
            "--files",
            "materials",
            "--question",
            "检索证据",
            "--output-json",
            str(tmp_path / "result.json"),
            "--embed-base-url",
            "http://127.0.0.1:8081",
            "--embed-model",
            "local-embedding",
        ]
    )

    assert code == 0
    assert captured["command"][:2] == ["llamaindex-cli", "rag"]
    assert captured["env"]["OPENAI_BASE_URL"] == "https://provider.example/v1"
    assert captured["env"]["OPENAI_MODEL"] == "gpt-test"
    assert captured["env"]["SENIOR_EXAM_EMBED_BASE_URL"] == "http://127.0.0.1:8081"
    assert captured["env"]["SENIOR_EXAM_EMBED_MODEL"] == "local-embedding"
    payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["stdout"] == "中文结果"


def test_llamaindex_wrapper_fails_closed_when_cli_missing(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
model_provider = "custom"
model = "gpt-test"

[model_providers.custom]
base_url = "https://provider.example/v1"
""".strip(),
        encoding="utf-8",
    )
    output_json = tmp_path / "missing-cli.json"

    monkeypatch.setattr("llamaindex_rag.shutil.which", lambda value: None)

    code = llamaindex_rag.main(
        [
            "--codex-config",
            str(config),
            "--executable",
            "missing-llamaindex-cli",
            "--files",
            "materials",
            "--question",
            "检索证据",
            "--output-json",
            str(output_json),
        ]
    )

    assert code == 127
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert "LlamaIndex CLI executable not found" in payload["stderr"]
