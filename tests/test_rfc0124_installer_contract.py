"""RFC-0124 installer / portal contract tests."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer" / "windows"
ISS = INSTALLER_DIR / "Jarvis.iss"
CLEAN = INSTALLER_DIR / "clean-reinstall-jarvis.ps1"
OWNED = INSTALLER_DIR / "owned-paths.ps1"
FORCE_STOP = INSTALLER_DIR / "force-stop-jarvis.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_clean_reinstall_scripts_exist():
    assert CLEAN.is_file()
    assert OWNED.is_file()


def test_clean_script_sequence_and_logs():
    text = _read(CLEAN)
    lower = text.lower()
    assert "force-stop-jarvis.ps1" in lower
    assert "missing" in lower or "abort" in lower
    assert "jarvis-clean-reinstall.log" in lower
    assert "clean-reinstall.log" in lower
    assert "license-issuer" in lower
    assert "setup-not-found" in lower or "setup path" in lower
    assert "wipe-incomplete" in lower or "leftover" in lower


def test_owned_paths_blocks_appdata_whole_tree():
    text = _read(OWNED)
    assert "LocalApplicationData" in text
    assert "Test-IsSafeJarvisInstallDir" in text
    assert "license-issuer" in text


def test_jarvis_iss_wires_clean_reinstall_helper():
    text = _read(ISS)
    lower = text.lower()
    assert "clean-reinstall-jarvis.ps1" in lower
    assert "runcleanreinstallownedwipe" in lower.replace("_", "")
    assert "jarvisownedpathskey" in lower.replace("_", "")
    assert "recordownedpathsregistry" in lower.replace("_", "")
    assert "no polite fallback" in lower


def test_jarvis_iss_no_polite_force_stop_fallback():
    text = _read(ISS)
    assert "falling back to stop-jarvis.ps1" not in text.lower()
    uninstall = text[text.index("GetUninstallForceStopParameters") :]
    assert "stop-jarvis.ps1" not in uninstall.split("end;", 1)[0].lower()


def test_force_stop_supports_multiple_roots():
    text = _read(FORCE_STOP)
    assert "InstallRoots" in text
    assert "Invoke-ForceStopSingleRoot" in text


def test_backend_api_wiring():
    main = _read(REPO_ROOT / "backend" / "app" / "main.py")
    assert "installer.router" in main
    api = _read(REPO_ROOT / "backend" / "app" / "api" / "installer.py")
    assert "/clean-reinstall/preview" in api
    assert "/clean-reinstall/start" in api
    launch = _read(REPO_ROOT / "backend" / "app" / "installer" / "clean_reinstall.py")
    assert "force-stop-jarvis.ps1 is missing" in launch
    assert "DETACHED_PROCESS" in launch or "Popen" in launch


def test_advanced_settings_includes_clean_card():
    pane = _read(REPO_ROOT / "frontend" / "src" / "settings" / "AdvancedSettingsPane.tsx")
    assert "CleanReinstallCard" in pane
