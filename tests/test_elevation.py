from types import SimpleNamespace

import pytest

from app.runtime import elevation as elev


def test_elevation_hint_does_not_tell_the_owner_to_run_a_command(monkeypatch):
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda: False)
    snap = elev.snapshot()
    hint = str(snap["logon_task_hint"]).lower()
    assert "registerlogontask" not in hint
    assert "start-jarvis" not in hint
    assert snap["needs_uac"] is True
    assert "approve" in hint


def test_prompt_windows_uac_uses_runas(monkeypatch):
    captured: dict[str, object] = {}

    class Shell32:
        def ShellExecuteW(self, hwnd, op, file, params, directory, show):
            captured["op"] = op
            captured["file"] = file
            captured["params"] = params
            return 42

    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda: False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(shell32=Shell32())),
    )
    result = elev.prompt_windows_uac()
    assert result["prompted"] is True
    assert captured["op"] == "runas"
    assert "powershell" in str(captured["file"]).lower()
    assert "-RegisterLogonTask" in str(captured["params"])
    assert "-NoBrowser" in str(captured["params"])


def test_logon_task_registered_caches_schtasks_probe(monkeypatch):
    elev.invalidate_logon_task_cache()
    calls = {"n": 0}

    def fake_query():
        calls["n"] += 1
        return True

    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "_query_logon_task_registered", fake_query)
    monkeypatch.setattr(elev, "_LOGON_TASK_CACHE_TTL_S", 60.0)

    assert elev.logon_task_registered() is True
    assert elev.logon_task_registered() is True
    assert calls["n"] == 1

    elev.invalidate_logon_task_cache()
    assert elev.logon_task_registered() is True
    assert calls["n"] == 2

    assert elev.logon_task_registered(force=True) is True
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_api_health_does_not_invoke_schtasks_on_repeat(monkeypatch):
    """Cold-start polls /api/health often; schtasks must not run every time."""
    from app.main import health

    elev.invalidate_logon_task_cache()
    calls = {"n": 0}

    def fake_query():
        calls["n"] += 1
        return False

    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "_query_logon_task_registered", fake_query)
    monkeypatch.setattr(elev, "_LOGON_TASK_CACHE_TTL_S", 60.0)
    monkeypatch.setattr(elev, "is_elevated", lambda: False)

    first = await health()
    second = await health()
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["logon_task_registered"] is False
    assert second["logon_task_registered"] is False
    assert calls["n"] == 1
