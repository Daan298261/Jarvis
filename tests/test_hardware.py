from app.hardware import _office_installed


def test_office_probe_is_false_off_windows(monkeypatch):
    monkeypatch.setattr("app.hardware.platform.system", lambda: "Linux")
    assert _office_installed() is False


def test_office_probe_does_not_dispatch(monkeypatch):
    monkeypatch.setattr("app.hardware.platform.system", lambda: "Windows")

    def boom(*args, **kwargs):
        raise AssertionError("Office probe must not Dispatch COM")

    import sys
    import types

    fake_win32 = types.ModuleType("win32com")
    fake_client = types.ModuleType("win32com.client")
    fake_client.Dispatch = boom
    fake_win32.client = fake_client
    monkeypatch.setitem(sys.modules, "win32com", fake_win32)
    monkeypatch.setitem(sys.modules, "win32com.client", fake_client)

    class _Missing:
        def OpenKey(self, *args, **kwargs):
            raise OSError("missing")

    fake_winreg = types.ModuleType("winreg")
    fake_winreg.HKEY_LOCAL_MACHINE = 1
    fake_winreg.OpenKey = _Missing().OpenKey
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr("app.hardware.Path.exists", lambda self: False)
    assert _office_installed() is False
