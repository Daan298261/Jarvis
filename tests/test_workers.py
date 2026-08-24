import sys

import pytest

from app.tools.capabilities import optional_workers
from app.tools.computer_use import CuaTool, UFOTool
from app.workers.computer import CuaBackend, NativeWindowsBackend, UFOBackend, preferred_computer_backend


def test_ufo_and_cua_are_integrated_even_when_missing():
    workers = {item["id"]: item for item in optional_workers()}
    assert workers["ufo"]["status"] in {"missing", "ready"}
    assert workers["cua"]["status"] in {"missing", "ready"}
    assert workers["ufo"]["status"] != "not_integrated"
    assert workers["cua"]["status"] != "not_integrated"


def test_ufo_command_builder_uses_module_or_cli():
    backend = UFOBackend()
    module_cmd = backend.build_command("click Save in Notepad", app="Notepad", kind="python-module:ufo")
    assert module_cmd[:4] == [sys.executable, "-m", "ufo", "--task"]
    assert "click Save in Notepad" in module_cmd
    assert module_cmd[-2:] == ["--app", "Notepad"]
    cli_cmd = backend.build_command("open Calculator", kind="cli:ufo")
    assert cli_cmd[:3] == ["ufo", "--task", "open Calculator"]


def test_cua_command_builder_uses_run_for_cli():
    backend = CuaBackend()
    cli_cmd = backend.build_command("focus the window", app="Word", kind="cli:cua")
    assert cli_cmd[:4] == ["cua", "run", "--task", "focus the window"]
    assert cli_cmd[-2:] == ["--app", "Word"]
    module_cmd = backend.build_command("type hello", kind="python-module:cua")
    assert module_cmd[:4] == [sys.executable, "-m", "cua", "--task"]


@pytest.mark.asyncio
async def test_missing_ufo_and_cua_point_at_native_desktop():
    ufo = await UFOTool().execute(action="run", goal="click File in Notepad")
    cua = await CuaTool().execute(action="run", goal="click File in Notepad")
    assert ufo.success is False
    assert cua.success is False
    assert "desktop" in (ufo.error or "").lower()
    assert "desktop" in (cua.error or "").lower()
    empty = await UFOTool().execute(action="run", goal="  ")
    assert empty.success is False
    assert "goal is required" in (empty.error or "")


def test_preferred_backend_falls_back_to_native_when_workers_missing():
    chosen = preferred_computer_backend()
    assert isinstance(chosen, (NativeWindowsBackend, UFOBackend, CuaBackend))
    if not UFOBackend().available() and not CuaBackend().available():
        assert isinstance(chosen, NativeWindowsBackend)
