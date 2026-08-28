"""Structural checks for Windows shell (tray + uninstall stop) — no Windows required."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAY_SCRIPT = REPO_ROOT / "installer" / "windows" / "jarvis-tray.ps1"
START_SCRIPT = REPO_ROOT / "start-jarvis.ps1"
STOP_SCRIPT = REPO_ROOT / "stop-jarvis.ps1"
ISS = REPO_ROOT / "installer" / "windows" / "Jarvis.iss"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tray_helper_exists_with_required_menu():
    assert TRAY_SCRIPT.is_file()
    text = _read(TRAY_SCRIPT)
    for needle in (
        "Open portal",
        "Start",
        "Stop",
        "Quit",
        "127.0.0.1:4780",
        "start-jarvis.ps1",
        "stop-jarvis.ps1",
    ):
        assert needle in text, f"jarvis-tray.ps1 should mention {needle!r}"


def test_start_jarvis_launches_tray_helper():
    text = _read(START_SCRIPT)
    assert "jarvis-tray.ps1" in text
    assert "Start-TrayHelper" in text


def test_stop_jarvis_still_mentions_llama_server():
    text = _read(STOP_SCRIPT)
    assert "llama-server" in text.lower()


def test_stop_jarvis_can_stop_tray_for_uninstall():
    text = _read(STOP_SCRIPT)
    assert "IncludeTray" in text
    assert "jarvis-tray" in text


def test_jarvis_iss_uninstall_stops_processes():
    text = _read(ISS)
    assert "[UninstallRun]" in text
    lower = text.lower()
    assert "stop-jarvis.ps1" in lower
    assert "includetray" in lower.replace("-", "")


def test_jarvis_iss_modify_stops_processes_via_prepare_to_install():
    text = _read(ISS)
    assert "[Code]" in text
    assert "PrepareToInstall" in text
    assert "IsUpgrade()" in text
    lower = text.lower()
    assert "stop-jarvis.ps1" in lower
    assert "includetray" in lower.replace("-", "")
    assert "modify" in lower
