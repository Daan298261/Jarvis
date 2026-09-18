"""RFC-0093 contract tests: force-stop, bounded bootstrap, durable logs (no Windows required)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer" / "windows"
ISS = INSTALLER_DIR / "Jarvis.iss"
FORCE_STOP = INSTALLER_DIR / "force-stop-jarvis.ps1"
RUN_BOOTSTRAP = INSTALLER_DIR / "run-installer-bootstrap.ps1"
BOOTSTRAP = INSTALLER_DIR / "bootstrap.ps1"
STOP = REPO_ROOT / "stop-jarvis.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_force_stop_script_exists_and_logs_pids():
    text = _read(FORCE_STOP)
    assert "installer-stop.log" in text
    assert "force-kill PID=" in text
    assert "InstallRoot" in text
    assert "InstallRoots" in text
    assert "MaxWaitSeconds" in text
    assert "stop-jarvis.ps1" in text


def test_force_stop_binds_ciminstance_not_managementobject():
    """Get-CimInstance returns CimInstance; a ManagementObject param fails every bind."""
    text = _read(FORCE_STOP)
    assert "[System.Management.ManagementObject]$Proc" not in text.replace(" ", "")
    assert "Get-CimInstance" in text
    assert "$procId =" in text
    assert "Stop-Process -Id $procId" in text
    assert "$pid =" not in text.lower()
    assert "CheckOnly" in text
    assert "ProtectedPids" in text
    assert "jarvissetup" in text.lower()
    assert "force-stop-jarvis" in text
    assert "Jarvis-installer-stop.log" in text
    assert "python|pythonw" in text
    assert "node|npm|java" in text


def test_jarvis_iss_wires_force_stop_before_prepare():
    text = _read(ISS)
    lower = text.lower()
    assert "force-stop-jarvis.ps1" in lower
    assert "stopjarvisprocessesforprepare" in lower.replace("_", "")
    assert "close jarvis and try again" in lower
    assert "installer-stop.log" in lower
    assert "getbootstraprunparameters" in lower.replace("_", "")
    assert "run-installer-bootstrap.ps1" in lower
    assert "bootstrapskipheavy" in lower.replace("_", "")


def test_jarvis_iss_uninstall_uses_force_stop():
    text = _read(ISS)
    assert "GetUninstallForceStopParameters" in text
    assert "force-stop-jarvis.ps1" in text.lower()


def test_run_installer_bootstrap_has_watchdog():
    text = _read(RUN_BOOTSTRAP)
    assert "MaxMinutes" in text
    assert "bootstrap.log" in text
    assert "timed out" in text.lower()
    assert "bootstrap.ps1" in text


def test_bootstrap_skip_heavy_and_step_timeout():
    text = _read(BOOTSTRAP)
    assert "SkipHeavyPrepare" in text
    assert "Invoke-ProcessWithTimeout" in text
    assert "bootstrap.log" in text
    assert "Test-HeavyPrepareSkippable" in text


def test_stop_jarvis_force_kill_lockers_switch():
    text = _read(STOP)
    assert "ForceKillLockers" in text
    assert "force-stop-jarvis.ps1" in text
