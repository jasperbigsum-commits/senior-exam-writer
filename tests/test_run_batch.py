from __future__ import annotations

import json
from pathlib import Path
import subprocess

from run_batch import main


def test_run_batch_prepare_only_does_not_start_embedding(monkeypatch, tmp_path, capsys) -> None:
    material = tmp_path / "material.md"
    material.write_text("# 第一章\n批量准备材料。", encoding="utf-8")
    output_dir = tmp_path / "batch"

    def fail_if_runtime_starts(*_args, **_kwargs):
        raise AssertionError("prepare-only must not start llama-server")

    monkeypatch.setattr("run_batch.launch_embedding_server", fail_if_runtime_starts)

    code = main(
        [
            "--prepare-only",
            "--requirements",
            "根据材料生成考试题。",
            "--input",
            str(material),
            "--output-dir",
            str(output_dir),
            "--db",
            str(tmp_path / "exam.sqlite"),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "prepare_only"
    assert payload["prepare"]["source_count"] == 1
    assert (output_dir / "prepare_report.json").exists()


def test_run_batch_managed_mode_auto_selects_loopback_port_and_stops_server(monkeypatch, tmp_path, capsys) -> None:
    material = tmp_path / "material.md"
    material.write_text("# 第一章\n批量入库材料。", encoding="utf-8")
    output_dir = tmp_path / "batch"
    stopped = []

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

    def fake_resolve_embedding_model(**_kwargs):
        model = tmp_path / "Qwen3-Embedding-0.6B-Q8_0.gguf"
        model.write_bytes(b"fake")
        return model, {"mode": "explicit_file"}

    def fake_launch_embedding_server(command, log_path):
        assert "--host" in command
        assert "127.0.0.1" in command
        assert "--port" in command
        assert "8081" not in command
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        return FakeProcess()

    def fake_run_cmd(args, *, cwd):
        command = " ".join(args)
        if "ingest" in args:
            assert "--embed-url" in args
            embed_url = args[args.index("--embed-url") + 1]
            assert embed_url.startswith("http://127.0.0.1:")
            assert not embed_url.endswith(":8081")
        return {"command": command, "returncode": 0, "stdout": "", "stderr": ""}

    def fake_stop_process(process):
        stopped.append(process)

    monkeypatch.setattr("run_batch.find_free_port", lambda: 49152)
    monkeypatch.setattr("run_batch.resolve_embedding_model", fake_resolve_embedding_model)
    monkeypatch.setattr("run_batch.resolve_llama_server", lambda value: "llama-server")
    monkeypatch.setattr("run_batch.launch_embedding_server", fake_launch_embedding_server)
    monkeypatch.setattr("run_batch.wait_for_embedding_ready", lambda **_kwargs: {"ok": True, "dimension": 1024})
    monkeypatch.setattr("run_batch.run_cmd", fake_run_cmd)
    monkeypatch.setattr("run_batch.stop_process", fake_stop_process)

    code = main(
        [
            "--requirements",
            "根据材料生成考试题。",
            "--input",
            str(material),
            "--output-dir",
            str(output_dir),
            "--db",
            str(tmp_path / "exam.sqlite"),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "managed_embedding_batch"
    assert payload["embed_url"] == "http://127.0.0.1:49152"
    assert payload["server_stopped"] is True
    assert stopped


def test_run_batch_managed_mode_fails_closed_and_stops_server(monkeypatch, tmp_path, capsys) -> None:
    material = tmp_path / "material.md"
    material.write_text("# 第一章\n批量入库材料。", encoding="utf-8")
    output_dir = tmp_path / "batch"
    stopped = []

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

    def fake_resolve_embedding_model(**_kwargs):
        model = tmp_path / "Qwen3-Embedding-0.6B-Q8_0.gguf"
        model.write_bytes(b"fake")
        return model, {"mode": "explicit_file"}

    def fake_run_cmd(args, *, cwd):
        if "ingest" in args:
            return {"command": " ".join(args), "returncode": 1, "stdout": "", "stderr": "编码正常：失败"}
        return {"command": " ".join(args), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("run_batch.find_free_port", lambda: 49153)
    monkeypatch.setattr("run_batch.resolve_embedding_model", fake_resolve_embedding_model)
    monkeypatch.setattr("run_batch.resolve_llama_server", lambda value: "llama-server")
    monkeypatch.setattr("run_batch.launch_embedding_server", lambda command, log_path: FakeProcess())
    monkeypatch.setattr("run_batch.wait_for_embedding_ready", lambda **_kwargs: {"ok": True, "dimension": 1024})
    monkeypatch.setattr("run_batch.run_cmd", fake_run_cmd)
    monkeypatch.setattr("run_batch.stop_process", lambda process: stopped.append(process))

    code = main(
        [
            "--requirements",
            "根据材料生成考试题。",
            "--input",
            str(material),
            "--output-dir",
            str(output_dir),
            "--db",
            str(tmp_path / "exam.sqlite"),
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert "ingest failed" in payload["error"]
    assert stopped


def test_run_batch_uses_utf8_for_subprocess_output(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_subprocess_run(args, **kwargs):
        calls.append(kwargs)

        class Completed:
            returncode = 0
            stdout = "中文输出"
            stderr = ""

        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    from run_batch import run_cmd

    result = run_cmd(["uv", "run", "python", "--version"], cwd=tmp_path)

    assert result["returncode"] == 0
    assert result["stdout"] == "中文输出"
    assert calls[0]["encoding"] == "utf-8"
    assert calls[0]["errors"] == "replace"
