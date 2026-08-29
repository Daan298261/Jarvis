"""Cross-platform checks for the Windows installer sources (no Windows required)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer" / "windows"
BOOTSTRAP = INSTALLER_DIR / "bootstrap.ps1"
ISS = INSTALLER_DIR / "Jarvis.iss"
BUILD_SCRIPT = INSTALLER_DIR / "build-installer.ps1"
README = INSTALLER_DIR / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_installer_files_exist():
    assert BOOTSTRAP.is_file()
    assert ISS.is_file()
    assert BUILD_SCRIPT.is_file()
    assert README.is_file()


def test_bootstrap_covers_required_steps():
    text = _read(BOOTSTRAP).lower()
    for needle in (
        ".venv",
        "requirements.txt",
        "playwright",
        "npm",
        "llama-server",
        "qwen3.5-9b",
        "start-jarvis",
        "winget",
    ):
        assert needle in text, f"bootstrap.ps1 should mention {needle!r}"


def test_bootstrap_27b_is_optional_switch_only():
    text = _read(BOOTSTRAP)
    assert "InstallExpert27B" in text
    # Default path must not always download 27B.
    assert "if ($InstallExpert27B)" in text
    lower = text.lower()
    assert "install by default" not in lower
    # 27B download should be gated behind the switch.
    assert text.index("if ($InstallExpert27B)") < text.index("Qwen3.5-27B")


def test_jarvis_iss_wiring():
    text = _read(ISS)
    assert "bootstrap.ps1" in text
    assert "Start Jarvis" in text
    assert "Stop Jarvis" in text
    lower = text.lower()
    assert "models" in lower and "excludes" in lower
    assert "runtime" in lower
    assert "start-jarvis.ps1" in lower


def test_build_script_invokes_iscc():
    text = _read(BUILD_SCRIPT)
    assert "iscc" in text.lower()
    assert "JarvisSetup.exe" in text
    lower = text.lower()
    assert "localappdata" in lower or r"programs\inno setup 6" in lower


def test_readme_documents_build_oneliner():
    text = _read(README)
    assert "build-installer.ps1" in text
    assert "JarvisSetup.exe" in text


def test_optional_tauri_shell_sources():
    """Tauri + sidecar are additive; Inno remains the landed JarvisSetup.exe path."""
    release = REPO_ROOT / "scripts" / "build-windows-release.ps1"
    sidecar = REPO_ROOT / "scripts" / "build-backend-sidecar.ps1"
    tauri_conf = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
    assert release.is_file()
    assert sidecar.is_file()
    assert tauri_conf.is_file()
    release_text = _read(release).lower()
    assert "build-backend-sidecar.ps1" in release_text
    assert "tauri" in release_text
    assert "inno" in release_text or "installer\\windows" in release_text
    sidecar_text = _read(sidecar).lower()
    assert "pyinstaller" in sidecar_text
    assert "onedir" in sidecar_text or "one-folder" in sidecar_text or "--onedir" in sidecar_text
    conf = _read(tauri_conf)
    assert "Jarvis" in conf
    assert "nsis" in conf.lower()
