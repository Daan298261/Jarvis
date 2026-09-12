from __future__ import annotations

import pytest

from app.main import app  # noqa: F401 — load tool registry before workers.computer
from app.workers.computer import ComputerUseBackend, NativeWindowsBackend, preferred_computer_backend


def test_computer_use_backend_probe_is_structured():
    backend = ComputerUseBackend()
    probe = backend.probe()
    assert probe["id"] == "computer"
    assert probe["available"] is False
    assert probe["status"] == "unavailable"
    assert "not available" in probe["detail"]


def test_computer_use_backend_build_command_is_empty_by_default():
    assert ComputerUseBackend().build_command("open notepad", app="notepad") == []


@pytest.mark.asyncio
async def test_computer_use_backend_run_requires_goal():
    result = await ComputerUseBackend().run("")
    assert result.success is False
    assert "goal is required" in result.error


@pytest.mark.asyncio
async def test_computer_use_backend_run_degrades_when_unavailable():
    result = await ComputerUseBackend().run("click Save")
    assert result.success is False
    assert "desktop tool" in result.error


@pytest.mark.asyncio
async def test_computer_use_backend_run_invokes_command(monkeypatch):
    class ReadyBackend(ComputerUseBackend):
        id = "ready"
        name = "Ready worker"

        def available(self) -> bool:
            return True

        def build_command(self, goal, app=None, kind=None):
            return ["echo", goal]

    async def fake_invoke(self, command, timeout):
        assert command == ["echo", "click Save"]
        return "clicked", "", 0

    monkeypatch.setattr(ReadyBackend, "_invoke", fake_invoke)
    result = await ReadyBackend().run("click Save")
    assert result.success is True
    assert "clicked" in result.output
    assert result.data["backend"] == "ready"


def test_native_windows_backend_probe_does_not_raise():
    probe = NativeWindowsBackend().probe()
    assert probe["id"] == "windows_ui"
    assert "available" in probe


def test_preferred_computer_backend_never_raises():
    backend = preferred_computer_backend()
    assert isinstance(backend, ComputerUseBackend)
    assert backend.probe()["id"]
