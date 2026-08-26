"""Cross-platform checks for Windows installer / desktop packaging sources."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer" / "windows"
BOOTSTRAP = INSTALLER_DIR / "bootstrap.ps1"
ISS = INSTALLER_DIR / "Jarvis.iss"
BUILD_SCRIPT = INSTALLER_DIR / "build-installer.ps1"
README = INSTALLER_DIR / "README.md"
RELEASE = REPO_ROOT / "scripts" / "build-windows-release.ps1"
SIDECAR = REPO_ROOT / "scripts" / "build-backend-sidecar.ps1"
TAURI_CONF = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
RFC = REPO_ROOT / "docs" / "rfcs" / "0002-desktop-application-and-installer.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_installer_files_exist():
    assert BOOTSTRAP.is_file()
    assert ISS.is_file()
    assert BUILD_SCRIPT.is_file()
    assert README.is_file()
    assert RELEASE.is_file()
    assert SIDECAR.is_file()
    assert TAURI_CONF.is_file()
    assert RFC.is_file()


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
    assert "if ($InstallExpert27B)" in text
    lower = text.lower()
    assert "install by default" not in lower
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
    assert "build-installer.ps1" in text or "build-windows-release.ps1" in text
    assert "JarvisSetup.exe" in text or "Tauri" in text


def test_canonical_release_script_and_tauri():
    release = _read(RELEASE).lower()
    assert "build-backend-sidecar.ps1" in release
    assert "tauri" in release
    assert "nsis" in release or "bundle" in release
    sidecar = _read(SIDECAR).lower()
    assert "pyinstaller" in sidecar
    assert "onedir" in sidecar or "one-folder" in sidecar or "--onedir" in sidecar
    conf = _read(TAURI_CONF)
    assert "Jarvis" in conf
    assert "nsis" in conf.lower()
    rfc = _read(RFC).lower()
    assert "accepted" in rfc
    assert "tauri" in rfc
