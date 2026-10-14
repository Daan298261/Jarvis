from types import SimpleNamespace

import pytest

from app.runtime import elevation as elev


def test_elevation_hint_does_not_tell_the_owner_to_run_a_command(monkeypatch):
    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: False)
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_kwargs: False)
    snap = elev.snapshot()
    hint = str(snap["logon_task_hint"]).lower()
    assert "registerlogontask" not in hint
    assert "start-jarvis" not in hint
    assert snap["needs_uac"] is True
    assert snap["elevation_degraded"] is True
    assert "allow full pc control" in hint or "nothing to type" in hint


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
    monkeypatch.setattr(elev, "logon_task_registered", lambda **_kwargs: False)
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


def test_force_refresh_replaces_stale_cache_for_later_reads(monkeypatch):
    """force=True must atomically replace cache so later unforced reads see fresh value."""
    elev.invalidate_logon_task_cache()
    state = {"registered": False}
    calls = {"n": 0}

    def fake_query():
        calls["n"] += 1
        return state["registered"]

    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "_query_logon_task_registered", fake_query)
    monkeypatch.setattr(elev, "_LOGON_TASK_CACHE_TTL_S", 60.0)

    assert elev.logon_task_registered() is False
    assert calls["n"] == 1

    state["registered"] = True
    # Stale TTL cache still says False until force.
    assert elev.logon_task_registered() is False
    assert calls["n"] == 1

    assert elev.logon_task_registered(force=True) is True
    assert calls["n"] == 2
    # Later unforced reads must see the forced value (no re-query).
    assert elev.logon_task_registered() is True
    assert elev.snapshot()["logon_task_registered"] is True
    assert calls["n"] == 2


def test_prompt_windows_uac_force_refresh_does_not_return_stale_snap(monkeypatch):
    """Already-admin early return must not spread a pre-force negative snapshot."""
    elev.invalidate_logon_task_cache()
    state = {"registered": False}
    calls = {"n": 0}

    def fake_query():
        calls["n"] += 1
        return state["registered"]

    monkeypatch.setattr(elev.os, "name", "nt")
    monkeypatch.setattr(elev, "is_elevated", lambda: True)
    monkeypatch.setattr(elev, "_query_logon_task_registered", fake_query)
    monkeypatch.setattr(elev, "_LOGON_TASK_CACHE_TTL_S", 60.0)

    # Warm negative cache.
    assert elev.logon_task_registered() is False
    state["registered"] = True

    result = elev.prompt_windows_uac()
    assert result["ok"] is True
    assert result["prompted"] is False
    assert result["logon_task_registered"] is True
    assert result["needs_uac"] is False
    assert "already has administrator" in str(result["detail"]).lower()
    # Cache replaced: subsequent health-style reads stay fresh without another query burst.
    n_after = calls["n"]
    assert elev.logon_task_registered() is True
    assert calls["n"] == n_after


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
    assert first["elevated"] is False
    assert second["elevated"] is False
    assert "logon_task_registered" not in first
    assert "logon_task_registered" not in second
    assert calls["n"] == 0
