"""RFC-0136 contract tests: zombie-kill on Setup Next and start-jarvis (no Windows required)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer" / "windows"
ISS = INSTALLER_DIR / "Jarvis.iss"
FORCE_STOP = INSTALLER_DIR / "force-stop-jarvis.ps1"
START = REPO_ROOT / "start-jarvis.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_force_stop_rfc0136_port_health_and_identity():
    text = _read(FORCE_STOP)
    lower = text.lower()
    assert "4780" in text and "4781" in text
    assert "get-nettcpconnection" in lower or "netstat" in lower
    assert "closewait" in lower.replace("_", "") or "close-wait" in lower
    assert "/api/health" in lower
    assert "health-fail" in lower
    assert "stranger-holds-port" in lower
    assert "post-kill-tcp-recheck" in lower
    assert "IsJarvisUvicornBackend" in text
    assert r"app\.main" in text
    assert r"app\.mobile\.gateway" in text
    assert "supermemory-server" in lower
    assert "second-venv" in lower
    assert "exit-reason=ok" in lower
    assert "port-still-owned" in lower
    assert "no jarvis lockers and ports 4780/4781 clear" in lower
    assert "force-stop complete: no lockers under install tree" not in lower


def test_force_stop_does_not_claim_success_without_port_recheck():
    text = _read(FORCE_STOP)
    assert "post-kill-tcp-recheck" in text
    assert "Test-AnyJarvisPortStillBlocked" in text


def test_jarvis_iss_next_runs_force_stop_on_install_method_page():
    text = _read(ISS)
    next_fn = text[text.index("function NextButtonClick") : text.index("function ResolveForceStopScript")]
    lower = next_fn.lower()
    assert "forcestopjarvisunder" in lower.replace("_", "")
    assert "rfc-0136" in lower
    assert "still running and could not be stopped" in lower
    assert "installer-stop.log" in lower
    # Clean confirm cancel must not reach force-stop (early exit when Result false).
    assert "if not result then" in lower


def test_start_jarvis_probes_health_before_uvicorn_spawn():
    text = _read(START)
    lower = text.lower()
    health_idx = lower.index("/api/health")
    spawn_idx = lower.index("start-process")
    force_idx = lower.index("force-stop-jarvis.ps1")
    assert health_idx < force_idx or "test-jarvisbackendhealthy" in lower
    assert "adopt" in lower
    assert "force-stop-jarvis.ps1 not found" in lower
    # force-stop must run before Start-Process uvicorn when not adopting
    adopt_block = text[text.index("Test-JarvisBackendHealthy") : text.index("Write-Step \"Waiting for")]
    assert "force-stop-jarvis.ps1" in adopt_block
    assert adopt_block.index("force-stop-jarvis.ps1") < adopt_block.index("Start-Process")
    assert "$pidFile" in adopt_block


def test_start_jarvis_adopt_skips_force_stop_and_pid_file():
    text = _read(START)
    assert "$adoptExistingBackend" in text
    assert "adopting existing backend" in text.lower()
    spawn_section = text.split("$adoptExistingBackend", 1)[1].split("Write-Step \"Waiting for", 1)[0]
    assert "Set-Content $pidFile" in spawn_section
    assert spawn_section.count("Set-Content $pidFile") == 1
