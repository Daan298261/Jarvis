from types import SimpleNamespace

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
