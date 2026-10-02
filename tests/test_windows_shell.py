"""Structural checks for Windows shell (tray + uninstall stop) — no Windows required."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAY_SCRIPT = REPO_ROOT / "installer" / "windows" / "jarvis-tray.ps1"
START_SCRIPT = REPO_ROOT / "start-jarvis.ps1"
STOP_SCRIPT = REPO_ROOT / "stop-jarvis.ps1"
ISS = REPO_ROOT / "installer" / "windows" / "Jarvis.iss"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tray_defines_start_jarvis_and_full_control():
    """Start stays a normal launch; full control is the separate UAC path."""
    text = _read(TRAY_SCRIPT)
    start = text.split("function Start-Jarvis", 1)
    full = text.split("function Enable-FullControl", 1)
    assert len(start) == 2, "jarvis-tray.ps1 must define function Start-Jarvis"
    assert len(full) == 2, "jarvis-tray.ps1 must define function Enable-FullControl"
    start_body = start[1].split("\nfunction ", 1)[0]
    full_body = full[1].split("\nfunction ", 1)[0]
    assert "Verb RunAs" not in start_body
    assert "-NoBrowser" in start_body
    assert "start-jarvis.ps1" in text
    assert "Verb RunAs" in full_body
    assert "RegisterLogonTask" in full_body
    assert "{ Start-Jarvis }" in text
    assert "{ Enable-FullControl }" in text


def test_tray_helper_exists_with_required_menu():
    assert TRAY_SCRIPT.is_file()
    text = _read(TRAY_SCRIPT)
    for needle in (
        "Open portal",
        "Allow full PC control",
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


def test_start_jarvis_allows_voice_only_without_gguf():
    text = _read(START_SCRIPT)
    assert "JARVIS_SKIP_MODEL" in text
    assert "voice chatbot" in text.lower()
    assert "throw \"No GGUF found" not in text
    assert "throw \"llama-server.exe missing" not in text
    assert "Show-StartupFailure" in text
    assert "Press Enter to close" in text
    assert "RegisterLogonTask" in text
    assert "Register-ScheduledTask" in text
    assert "Verb RunAs" in text
    assert "JarvisElevatedBackend" in text
    assert "-ErrorAction Stop" in text
    assert "Remove-Item Env:JARVIS_SKIP_MODEL" in text
    assert "Start-ElevatedJarvisCopy" in text
    assert "JARVIS_SKIP_ELEVATION_PROMPT" in text
    assert "Windows will ask once" in text
    assert "Allow full PC control" in _read(TRAY_SCRIPT)


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
    assert "JarvisElevatedBackend" in text


def test_jarvis_iss_modify_stops_processes_via_prepare_to_install():
    text = _read(ISS)
    assert "[Code]" in text
    assert "PrepareToInstall" in text
    assert "StopJarvisProcessesForPrepare" in text
    assert "ForceStopJarvisUnder" in text
    assert "IsUpgrade()" not in text
    lower = text.lower()
    assert "force-stop-jarvis.ps1" in lower
    assert "includetray" in lower.replace("-", "")
    assert "modify" in lower
