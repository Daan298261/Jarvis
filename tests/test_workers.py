from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.base import ToolResult
from app.workers.code import (
    OpenInterpreterBackend,
    open_interpreter_status,
    resolve_code_backend,
    sandbox_working_directory,
)


def test_open_interpreter_is_catalogued_even_when_missing():
    status = open_interpreter_status()
    assert status["id"] == "open-interpreter"
    assert status["status"] in {"ready", "missing"}
    if not status["available"]:
        assert status["status"] == "missing"
        native = resolve_code_backend()
        assert native.name == "native"


def test_sandbox_rejects_paths_outside_allowed(tmp_path):
    allowed = [str(tmp_path)]
    inside = sandbox_working_directory(str(tmp_path / "proj"), allowed)
    assert inside == (tmp_path / "proj").resolve()
    with pytest.raises(PermissionError):
        sandbox_working_directory("/etc", allowed)


async def test_open_interpreter_missing_points_at_native_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.workers.code.open_interpreter_status",
        lambda: {"available": False, "module": False, "cli": None, "status": "missing"},
    )
    result = await OpenInterpreterBackend().run(
        "write hello.py",
        tmp_path,
        api_base="http://127.0.0.1:8088/v1",
        api_key="local",
        model="openai/Qwen3.5-27B",
        timeout=5,
    )
    assert result.success is False
    assert "not installed" in result.error.lower()
    assert "python" in result.error.lower()


async def test_open_interpreter_runs_injected_backend(tmp_path, monkeypatch):
    async def fake_run(self, instruction, working_directory, **kwargs):
        Path(working_directory, "ok.txt").write_text(instruction, encoding="utf-8")
        return ToolResult(True, "wrote ok.txt", data={"backend": "open-interpreter"})

    monkeypatch.setattr(
        "app.workers.code.open_interpreter_status",
        lambda: {"available": True, "module": True, "cli": None, "status": "ready"},
    )
    monkeypatch.setattr(OpenInterpreterBackend, "run", fake_run)
    backend = OpenInterpreterBackend()
    result = await backend.run("hello", tmp_path, api_base="http://x", api_key="k", model="m", timeout=5)
    assert result.success is True
    assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "hello"


async def test_code_worker_tool_requires_instruction(jarvis_env):
    from app.tools.registry import REGISTRY

    result = await REGISTRY.execute("code_worker", {})
    assert result.success is False
    assert "instruction" in result.error
