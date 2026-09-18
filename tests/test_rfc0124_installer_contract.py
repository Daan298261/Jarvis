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
    assert "jarvis-clean-reinstall.status.json" in lower
    assert "clean-reinstall.log" in lower
    assert "license-issuer" in lower
    assert "setup-not-found" in lower or "setup path" in lower
    assert "wipe-incomplete" in lower or "leftover" in lower


def test_owned_paths_blocks_appdata_whole_tree():
    text = _read(OWNED)
    assert "LocalApplicationData" in text
    assert "Test-IsSafeJarvisInstallDir" in text
    assert "license-issuer" in text


def test_jarvis_iss_code_comments_do_not_nest_inno_constants():
    """Block comments must not contain {tmp}/{app}; the inner brace ends the comment early."""
    text = _read(ISS)
    code = text[text.index("[Code]") :]
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{") or stripped.startswith("//"):
            continue
        if "{" in stripped[1:] and not stripped.startswith("{#"):
            raise AssertionError(
                f"Nested brace in Inno [Code] block comment (iscc parse error): {line!r}"
            )


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


def test_iss_extracts_hotfix_helpers_to_tmp():
    text = _read(ISS)
    assert "ExtractTemporaryFile('force-stop-jarvis.ps1')" in text
    assert "ExtractTemporaryFile('owned-paths.ps1')" in text
    assert "ExtractTemporaryFile('clean-reinstall-jarvis.ps1')" in text
    assert "ExtractTemporaryFile('reset-user-data.ps1')" in text
    init = text[text.index("function InitializeSetup") : text.index("procedure InitializeWizard")]
    assert "ExtractInstallerHelpers" in init
    prepare = text[text.index("function PrepareToInstall") :]
    assert "ExtractInstallerHelpers" in prepare


def test_iss_prefers_tmp_scripts_over_installed_copies():
    text = _read(ISS)
    force = text[text.index("function ResolveForceStopScript") : text.index("function ForceStopJarvisUnder")]
    assert force.index("{tmp}\\force-stop-jarvis.ps1") < force.index(
        "AppDir + '\\installer\\windows\\force-stop-jarvis.ps1'"
    )
    clean = text[text.index("function ResolveCleanReinstallScript") : text.index("function RunCleanReinstallOwnedWipe")]
    assert clean.index("{tmp}\\clean-reinstall-jarvis.ps1") < clean.index(
        "AppDir + '\\installer\\windows\\clean-reinstall-jarvis.ps1'"
    )


def test_remove_existing_does_not_hard_fail_on_missing_unins():
    text = _read(ISS)
    fn = text[text.index("function RemoveExistingApplication") : text.index("function ResolveResetUserDataScript")]
    assert "broken leftover tree" in fn.lower()
    assert "Result := False" in fn
    assert "Retry force-stop still found lockers" in fn
    assert "uninstaller exited 0" in fn.lower()


def test_detects_half_dead_leftover_tree_without_unins():
    text = _read(ISS)
    detect = text[text.index("function DetectExistingInstallation") : text.index("function IsSafeJarvisInstallDir")]
    assert "models" in detect
    assert "start-jarvis.ps1" in detect
    assert ".venv" in detect


def test_clean_wipe_does_not_trust_uninstall_exit_zero():
    text = _read(CLEAN)
    lower = text.lower()
    assert "exit 0 is not wipe success" in lower
    assert "-CheckOnly" in text
    assert "wipe retry" in lower
    assert "Join-Path $scriptDir" in text
    assert "force-stop-jarvis.ps1 missing" in lower


def test_backend_api_wiring():
    main = _read(REPO_ROOT / "backend" / "app" / "main.py")
    assert "installer.router" in main
    api = _read(REPO_ROOT / "backend" / "app" / "api" / "installer.py")
    assert "/clean-reinstall/owned-roots" in api
    assert "/clean-reinstall/preview" in api
    assert "/clean-reinstall/status" in api
    assert "/clean-reinstall/start" in api
    assert "UX API contract" in api
    assert "owned_root_entries" in api
    assert "confirm_token" in api
    launch = _read(REPO_ROOT / "backend" / "app" / "installer" / "clean_reinstall.py")
    assert "force-stop-jarvis.ps1 is missing" in launch
    assert "DETACHED_PROCESS" in launch or "Popen" in launch

