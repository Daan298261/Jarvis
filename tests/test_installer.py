"""Cross-platform checks for the Windows installer sources (no Windows required)."""

from pathlib import Path
import importlib.util
from types import SimpleNamespace
import json
import re
import struct
import tomllib
import sys

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
    assert (INSTALLER_DIR / "install-persona-voices.py").is_file()


def test_bootstrap_covers_required_steps():
    text = _read(BOOTSTRAP).lower()
    for needle in (
        ".venv",
        "requirements.txt",
        "ensure-ttspythonpackages",
        "ensure-layapythonpackage",
        "laya==0.3.21",
        "ensure-kokorovoice",
        "ensure-personavoices",
        "ensure-whispermodel",
        ".jarvis_faster_whisper_dir",
        "ensure-voicestudio",
        "ensure-pockettts",
        "ensure-umiollamabrain",
        "ensure-ollamacli",
        "install-persona-voices.py",
        "kokoro",
        "soundfile",
        "playwright",
        "npm",
        "mcp\\package-lock.json",
        "ensure-mcpconnectors",
        "llama-server",
        "downloading and installing llama.cpp",
        "qwen3.5-9b",
        "start-jarvis",
        "winget",
    ):
        assert needle in text, f"bootstrap.ps1 should mention {needle!r}"


def test_persona_setup_prepares_each_shared_neural_pack(monkeypatch):
    script = INSTALLER_DIR / "install-persona-voices.py"
    spec = importlib.util.spec_from_file_location("install_persona_voices", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    installed: list[str] = []
    profiles = {row.voice_profile_id: object() for row in module.ROSTER}
    monkeypatch.setattr(module, "get_catalog", lambda: SimpleNamespace(get=profiles.get))

    def install(profile):
        installed.append(next(key for key, value in profiles.items() if value is profile))
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(module, "install_voice_pack", install)

    assert module.main() == 0
    assert installed == list(dict.fromkeys(row.voice_profile_id for row in module.ROSTER))


def test_persona_setup_honors_selected_and_none_voice_packs(monkeypatch):
    script = INSTALLER_DIR / "install-persona-voices.py"
    spec = importlib.util.spec_from_file_location("install_persona_voices_subset", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    installed: list[str] = []
    profiles = {row.voice_profile_id: object() for row in module.ROSTER}
    monkeypatch.setattr(module, "get_catalog", lambda: SimpleNamespace(get=profiles.get))
    monkeypatch.setattr(
        module,
        "install_voice_pack",
        lambda profile: installed.append(next(key for key, value in profiles.items() if value is profile))
        or SimpleNamespace(ok=True),
    )
    assert module.main(["none"]) == 0
    assert installed == []
    assert module.main(["butler_original_v1", "chatterbox_expressive_en_v1"]) == 0
    assert installed == ["butler_original_v1", "chatterbox_expressive_en_v1"]


def test_installer_offers_voice_model_checkboxes():
    iss = _read(ISS)
    bootstrap = _read(BOOTSTRAP)
    wrapper = _read(INSTALLER_DIR / "run-installer-bootstrap.ps1")
    for needle in (
        'Name: "voicebutler"',
        'Name: "voicedry"',
        'Name: "voicetactical"',
        'Name: "voicesynthetic"',
        'Name: "voicechatterbox"',
        'GroupDescription: "Voice models:"',
        "SelectedVoiceProfiles",
        "-VoiceProfiles",
        "butler_original_v1",
        "chatterbox_expressive_en_v1",
    ):
        assert needle in iss, needle
    assert "$VoiceProfiles" in bootstrap
    assert "none selected" in bootstrap.lower()
    assert "$VoiceProfiles" in wrapper
    assert "stage-license-sidecar.ps1" in wrapper
    assert "$InstallerDir" in wrapper
    assert "checkboxes" in _read(README).lower()
    assert "neural voice" in _read(README).lower()


def test_anzu_local_alias_and_manager_are_packaged():
    iss = _read(ISS)
    hosts = INSTALLER_DIR / "manage-anzu-hosts.ps1"
    manager = REPO_ROOT / "start-anzu-manager.ps1"
    assert 'Name: "anzualias"' in iss
    assert 'Name: "dl_expert27b"' in iss and 'Flags: unchecked' in iss.split('Name: "dl_expert27b"', 1)[1].splitlines()[0]
    for selected in ("dl_voicestudio", "dl_pockettts", "dl_umi_brain"):
        line = next(line for line in iss.splitlines() if f'Name: "{selected}"' in line)
        assert "unchecked" not in line
    text = _read(hosts)
    assert "BEGIN ANZU LOCAL ALIAS" in text and "127.0.0.1 anzu" in text
    assert manager.is_file()
    assert "AnzuManager.exe" in iss
    assert "start-anzu-manager.ps1" in iss
    force_stop = _read(INSTALLER_DIR / "force-stop-jarvis.ps1")
    assert "PreserveManager" in force_stop


def test_installer_registers_elevated_logon_task():
    iss = _read(ISS)
    assert 'Name: "elevatedlogon"' in iss
    assert "RegisterLogonTask" in iss
    assert "JarvisElevatedBackend" in iss
    assert "Tasks: elevatedlogon" in iss
    assert 'Flags: checkedonce' in iss
    start = (REPO_ROOT / "start-jarvis.ps1").read_text(encoding="utf-8")
    assert "Verb RunAs" in start
    assert "JarvisElevatedBackend" in start


def test_bootstrap_27b_is_optional_switch_only():
    text = _read(BOOTSTRAP)
    assert "InstallExpert27B" in text
    assert "InstallLocalLLM" in text
    # Default path must not always download 27B.
    assert "if ($InstallExpert27B)" in text
    lower = text.lower()
    assert "install by default" not in lower
    # 27B download should be gated behind the switch.
    assert text.index("if ($InstallExpert27B)") < text.index("Qwen3.5-27B")
    assert "if (-not $InstallLocalLLM)" in text


def test_jarvis_iss_wiring():
    text = _read(ISS)
    assert "bootstrap.ps1" in text
    assert "run-installer-bootstrap.ps1" in text
    assert "stage-license-sidecar.ps1" in text
    assert "StageLicenseSidecar" in text
    assert "-InstallerDir" in text
    assert "-AppRoot" in text
    assert "force-stop-jarvis.ps1" in text
    assert "Start Jarvis" in text
    assert "Stop Jarvis" in text
    assert "dl_kokoro" in text
    assert "dl_personavoices" in text
    assert "dl_whisper" in text
    assert "dl_voicestudio" in text
    assert "dl_pockettts" in text
    assert "dl_umi_brain" in text
    assert "-InstallWhisper" in text
    assert "-InstallVoiceStudio" in text
    assert "-InstallPocketTTS" in text
    assert "-InstallUmiBrain" in text
    lower = text.lower()
    assert "models" in lower and "excludes" in lower
    assert "release\\" in lower or "release\\*" in lower
    assert "releases\\" in lower or "releases\\*" in lower
    assert "_release_upload" in lower
    assert ".vendor" in lower
    assert "installer-build" in lower
    assert "runtime" in lower
    assert "start-jarvis.ps1" in lower
    assert "diskspanning=yes" in lower
    assert "step=integrations" in lower
    assert "runhidden" in lower
    assert "desktopshellinstalled" in lower.replace("_", "")
    assert "function DesktopShellInstalled" in text


def test_release_installer_includes_launch_module_and_current_portal():
    """1.5.0 excluded app.runtime and reused an old frontend/dist on upgrade."""
    iss = _read(ISS)
    assert 'Source: "..\\..\\backend\\app\\runtime\\*"; DestDir: "{app}\\backend\\app\\runtime"' in iss
    assert 'Source: "..\\..\\frontend\\dist\\*"; DestDir: "{app}\\frontend\\dist"' in iss
    assert (REPO_ROOT / "backend" / "app" / "runtime" / "elevation.py").is_file()
    build = _read(BUILD_SCRIPT)
    assert 'frontend\\dist\\index.html' in build
    assert 'Portal asset missing:' in build


def test_installer_retries_elevated_stop_and_blocks_failed_uninstall():
    iss = _read(ISS)
    assert "ShellExec('runas', 'powershell.exe'" in iss
    assert "function InitializeUninstall: Boolean;" in iss
    assert "Result := ForceStopJarvisUnder(ExpandConstant('{app}'));" in iss


def test_startup_does_not_kill_its_launcher_before_backend_is_ready():
    start = _read(REPO_ROOT / "start-jarvis.ps1")
    stop = _read(INSTALLER_DIR / "force-stop-jarvis.ps1")
    assert "Local\\JarvisStartup" in start
    assert "if ($portOccupied)" in start
    assert "-StartupCleanup" in start
    assert "Release-StartupLock" in start
    assert "if ($StartupCleanup -and ([string]$Proc.CommandLine) -match 'start-jarvis\\.ps1')" in stop


def test_desktop_sidecar_resolves_installed_root(monkeypatch, tmp_path):
    from app.config import repo_root
    from jarvis_sidecar import _resolve_root

    install_root = tmp_path / "Jarvis"
    sidecar = install_root / "desktop" / "sidecars" / "jarvis-backend" / "jarvis-backend.exe"
    monkeypatch.delenv("JARVIS_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(sidecar))
    assert _resolve_root() == install_root
    monkeypatch.setenv("JARVIS_ROOT", str(install_root))
    assert _resolve_root() == install_root
    assert repo_root() == install_root

    shell = _read(REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs")
    assert 'root.join("desktop").join("sidecars").join("jarvis-backend")' in shell
    assert shell.index('let prepared_python = root.join(".venv")') < shell.index("let candidates = [")


def test_jarvis_iss_code_uses_supported_registry_apis_only():
    """Inno [Code] has RegWriteStringValue but not Win32-style RegCreateKey (iscc fails)."""
    text = _read(ISS)
    lower = text.lower()
    assert "regcreatekey" not in lower
    assert "recordownedpathsregistry" in lower.replace("_", "")
    assert "jarvisownedpathskey" in lower.replace("_", "")
    assert "regwritestringvalue" in lower


def test_existing_install_upgrade_and_removal_choices_are_wired():
    text = _read(ISS)
    lower = text.lower()
    assert "detectexistinginstallation" in lower
    assert "comparepackedversion" in lower
    assert "existing jarvis installation found" in lower
    assert "upgrade to jarvis" in lower
    assert "reinstall jarvis" in lower
    assert "semi-clean reinstall" in lower
    assert "clean reinstall" in lower
    assert "reset-user-data.ps1" in lower
    assert "removeexistingapplication" in lower
    assert "/verysilent /suppressmsgboxes /norestart" in lower
    assert "clean-reinstall-jarvis.ps1" in lower
    assert "runcleanreinstallownedwipe" in lower.replace("_", "")
    assert "this cannot be undone" in lower
    assert "issafejarvisinstalldir" in lower


def test_installer_and_desktop_versions_match():
    iss_text = _read(ISS)
    installer_version = re.search(r'#define MyAppVersion "([^"]+)"', iss_text).group(1)
    cargo = tomllib.loads(_read(REPO_ROOT / "frontend" / "src-tauri" / "Cargo.toml"))
    tauri = json.loads(_read(REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"))
    backend = re.search(
        r'__version__ = "([^"]+)"',
        _read(REPO_ROOT / "backend" / "app" / "__init__.py"),
    ).group(1)
    package = json.loads(_read(REPO_ROOT / "frontend" / "package.json"))
    lock = json.loads(_read(REPO_ROOT / "frontend" / "package-lock.json"))
    cargo_lock = _read(REPO_ROOT / "frontend" / "src-tauri" / "Cargo.lock")
    gradle = _read(REPO_ROOT / "android" / "app" / "build.gradle.kts")
    assert installer_version == "1.5.3-beta"
    assert installer_version == backend
    assert cargo["package"]["version"] == installer_version
    assert tauri["version"] == installer_version
    assert package["version"] == installer_version
    assert lock["version"] == installer_version
    assert lock["packages"][""]["version"] == installer_version
    assert f'name = "jarvis"\nversion = "{installer_version}"' in cargo_lock
    assert f'versionName = "{installer_version}"' in gradle
    # Windows VERSIONINFO cannot carry a semver pre-release tag.
    assert "VersionInfoVersion={#MyAppVersion}.0" not in iss_text
    assert "VersionInfoVersion={#MyAppVersionCore}.0" in iss_text
    assert "MyAppVersionCore Copy(MyAppVersion, 1, Pos(\"-\" , MyAppVersion + \"-\") - 1)" in iss_text or (
        "MyAppVersionCore" in iss_text and 'Pos("-"' in iss_text
    )
    assert "function StripPreRelease" in iss_text


def test_reset_user_data_script_exists():
    script = INSTALLER_DIR / "reset-user-data.ps1"
    assert script.is_file()
    text = _read(script).lower()
    assert "jarvis.db" in text
    assert "workflows" in text
    assert "private_key" in text or "preserved" in text


def test_build_script_invokes_iscc():
    text = _read(BUILD_SCRIPT)
    assert "iscc" in text.lower()
    assert "JarvisSetup.exe" in text
    lower = text.lower()
    assert "localappdata" in lower or r"programs\inno setup 6" in lower
    assert "build-license-manager.ps1" in text
    assert "JarvisLicenseManager" in text
    assert "issue-release-unrestricted-license.ps1" in text
    assert "Unrestricted license issuance failed" in text
    assert "$Release" in text
    assert "Jarvis-unrestricted.jarvis-license" in text


def test_vendor_license_manager_is_excluded_from_inno_payload():
    iss = _read(ISS)
    assert "tools\\license_manager" in iss
    assert "JarvisLicenseManager.exe" in iss
    assert "manager_app.py" in iss
    assert "stage-license-sidecar.ps1" in iss
    for line in iss.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source:") and "JarvisLicenseManager" in stripped and "Excludes:" not in stripped:
            raise AssertionError("JarvisLicenseManager must not be copied into the customer payload")
    manager = INSTALLER_DIR / "build-license-manager.ps1"
    assert manager.is_file()
    manager_text = _read(manager)
    assert "JarvisLicenseManager" in manager_text
    assert "JARVIS_VENDOR_RELEASE" in manager_text
    assert "not in the public tree" in manager_text.lower() or "vendor-only" in manager_text.lower()
    assert not (REPO_ROOT / "tools" / "license_manager" / "__main__.py").is_file()
    assert not (REPO_ROOT / "backend" / "app" / "licensing" / "manager_app.py").is_file()


def test_inno_excludes_nested_jarvis_copies_and_releases():
    iss = _read(ISS)
    assert "Releases\\*" in iss
    assert "*\\Jarvis\\*" in iss
    assert "*\\Jarvis\\**" in iss


def test_installer_bundles_qwen35_2b_front_model():
    """Fresh installs ship the warm front lane next to the Ornith bootstrap GGUF."""
    from app.inference.profiles import PROFILES

    profile = PROFILES["front_2b"]
    iss = _read(ISS)
    payload = f"payload\\models\\{profile.repo_dir}\\{profile.filename}"
    dest = '{app}\\models\\' + profile.repo_dir
    source = next(
        line
        for line in iss.splitlines()
        if line.strip().startswith("Source:") and profile.filename in line and "Qwen3.5-2B-GGUF" in line
    )
    assert payload in source
    assert f'DestDir: "{dest}"' in source
    assert "ignoreversion" in source
    assert "deleteafterinstall" not in source.lower()
    front_block = iss.split("#ifndef SkipFrontModel", 1)[1].split("#endif", 1)[0]
    assert payload in front_block
    assert dest in front_block
    bootstrap_line = next(
        line for line in iss.splitlines() if "Ornith-1.5-9B-Q4_K_M.gguf" in line and line.strip().startswith("Source:")
    )
    assert "Flags: ignoreversion" in bootstrap_line
    assert iss.index("#ifndef SkipBootstrapModel") < iss.index("#ifndef SkipFrontModel")
    assert "semi-clean reinstall" in iss.lower()
    reset = _read(INSTALLER_DIR / "reset-user-data.ps1").lower()
    assert "models/" in reset
    assert "qwen3.5-2b" not in reset

    build = _read(BUILD_SCRIPT)
    assert "stage-front-model.ps1" in build
    assert build.index("stage-bootstrap-model.ps1") < build.index("stage-front-model.ps1")
    assert "/DSkipFrontModel=1" in build
    assert "Front model payload not ready" in build
    assert "Includes: Qwen3.5-2B Q4_K_M front-lane weights" in build
    reject = build.index("Release cuts cannot use -SkipFrontModel")
    window = build[max(0, reject - 250) : reject]
    assert "$Release" in window and "$SkipFrontModel" in window

    stage = _read(INSTALLER_DIR / "stage-front-model.ps1")
    assert "unsloth/Qwen3.5-2B-GGUF" in stage
    assert profile.filename in stage
    assert "1280835840" in stage
    assert "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223" in stage
    assert "JARVIS_FRONT_2B_GGUF" in stage
    assert r"models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf" in stage
    assert ".jarvis_front_2b_verified" in stage
    fast_path = stage.split("Test-Path -LiteralPath $Marker))", 1)[1].split("exit 0", 1)[0]
    assert "Get-FileHash" not in fast_path
    assert "$ExpectedSha" in fast_path
    assert "SHA-256" in stage

    bootstrap = _read(BOOTSTRAP)
    body = bootstrap.split("function Ensure-Front2bGguf", 1)[1].split("function Ensure-DefaultModels", 1)[0]
    assert r"models\Qwen3.5-2B-GGUF" in body
    assert profile.filename in body
    assert body.index("Write-Skip") < body.index("Invoke-HfDownload")
    assert "Ensure-Front2bGguf -VenvPython $VenvPython" in bootstrap
    assert bootstrap.index("Ensure-BootstrapGguf -VenvPython $VenvPython") < bootstrap.index(
        "Ensure-Front2bGguf -VenvPython $VenvPython"
    )

    readme = _read(README).lower()
    assert "qwen3.5-2b" in readme
    assert "models\\qwen3.5-2b-gguf" in readme
    assert "skipfrontmodel" in readme
    assert "warm front" in readme or "front model" in readme


def test_customer_deliverables_publish_to_gitignored_release_dir():
    """Every installer build copies the customer set into <repo>/release/."""
    gitignore = _read(REPO_ROOT / ".gitignore")
    assert "\nrelease/\n" in f"\n{gitignore}\n"
    build = _read(BUILD_SCRIPT)
    stage = _read(INSTALLER_DIR / "stage-release-folder.ps1")
    assert "[string]$DriveReleasesPath" in build
    assert "Publishing customer deliverables to release\\" in build
    invoke_line = next(
        line
        for line in build.splitlines()
        if "stage-release-folder.ps1" in line and line.lstrip().startswith("& powershell")
    )
    assert invoke_line.startswith("& powershell")
    assert "-StageVersionedHotfix" in build
    assert build.index("if ($Release)") < build.index("Publishing customer deliverables to release\\")
    assert build.index("-StageVersionedHotfix") < build.index(invoke_line)
    assert 'Join-Path $Root "release"' in stage
    assert "[string]$DriveReleasesPath" in stage
    assert "Customer deliverables copied from $ReleaseDir to $drive" in stage
    assert "JarvisSetup.exe" in stage
    assert "JarvisLicenseManager.exe" in stage
    assert "*.jarvis-license" in stage
    assert "*.apk" in stage
    assert "-setup.exe" in stage
    assert ".zip" in stage
    assert ".tar.gz" in stage
    readme = _read(README)
    assert "DriveReleasesPath" in readme
    assert "release\\" in readme
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "android-companion.yml")
    assert "publish_customer_release.py" in workflow
    android = _read(REPO_ROOT / "scripts" / "build_android.py")
    assert "publish_customer_release.py" in android
    assert "release_path" in android


def test_readme_documents_build_oneliner():
    text = _read(README)
    assert "build-installer.ps1" in text
    assert "JarvisSetup.exe" in text
    assert "ensure-vendor-issuer.ps1" in text
    assert "Jarvis-unrestricted.jarvis-license" in text
    assert "$Release" in text or "-Release" in text
    assert "1.4.6" in text


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
    assert "--hidden-import app.main" in sidecar_text
    assert "--collect-submodules app" in sidecar_text
    assert "--hidden-import aiosqlite" in sidecar_text
    conf = _read(tauri_conf)
    assert "ANZU" in conf or "Jarvis" in conf
    assert "nsis" in conf.lower()
    assert "stage-release-folder.ps1" in release_text
    assert "release" in release_text


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    assert data[12:16] == b"IHDR", path
    return struct.unpack(">II", data[16:24])


def _iss_sections(text: str) -> set[str]:
    return set(re.findall(r"(?m)^\[([^\]]+)\]\s*$", text))


def test_select_all_checkbox_is_wired_to_existing_lists():
    """Select all sits on every components/tasks checklist the script defines."""
    iss = _read(ISS)
    sections = _iss_sections(iss)
    lists = []
    if "Tasks" in sections:
        lists.append("TasksList")
    if "Components" in sections:
        lists.append("ComponentsList")
    assert lists, "installer should define [Tasks] and/or [Components]"

    assert "Caption := 'Select all'" in iss
    assert "TNewCheckBox" in iss
    assert "AllowGrayed" in iss
    assert "cbGrayed" in iss
    assert "ItemEnabled" in iss
    assert "ItemObject" in iss
    assert "procedure ApplySelectAll" in iss
    assert "procedure SelectAllClick" in iss
    assert "WizardSilent" in iss

    prepare = iss.split("procedure PrepareAnzuWizard", 1)[1].split("\nprocedure ", 1)[0]
    assert "WizardSilent" in prepare
    assert "ApplySelectAll" not in prepare
    for name in lists:
        assert f"WizardForm.{name}.OnClickCheck := @ChecklistClickCheck" in iss
        assert f"WizardForm.{name}" in prepare or f"WizardForm.{name}" in iss


def test_anzu_wizard_theme_assets_and_glow_timer():
    """Dark ANZU art is generated, and the glow timer is stopped on teardown."""
    iss = _read(ISS)
    assets = INSTALLER_DIR / "assets"
    script = assets / "render_wizard_assets.py"
    assert script.is_file()
    source = _read(script)
    for needle in (
        "#05070a",
        "#67dcff",
        "#d4a017",
        "1100",
        "0.85",
        "1.2",
        "0.65",
        "0.72",
        "FRAME_COUNT = 16",
        "boot-dot-pulse",
    ):
        assert needle in source, needle

    assert "WizardStyle=modern" in iss
    assert "WizardSmallImageBackColor=$0A0705" in iss
    assert "AnzuGlowIntervalMs = 69" in iss
    assert "AnzuGlowFrames = 16" in iss
    assert "CreateCallback(@GlowTimerProc)" in iss
    assert "PngImage.LoadFromFile" in iss
    assert "procedure DeinitializeSetup" in iss
    shutdown = iss.split("procedure DeinitializeSetup", 1)[1]
    assert "KillTimer(0, GlowTimerID)" in shutdown
    assert "GlowTimerID := 0" in shutdown

    large = (
        (164, 314),
        (202, 386),
        (240, 459),
        (269, 515),
        (290, 556),
        (315, 604),
        (336, 643),
        (403, 772),
        (430, 824),
    )
    small = (58, 71, 77, 85, 97, 103, 112, 116, 124, 129, 143, 147, 159)
    image_directive = next(line for line in iss.splitlines() if line.startswith("WizardImageFile="))
    small_directive = next(line for line in iss.splitlines() if line.startswith("WizardSmallImageFile="))
    for width, height in large:
        name = f"wizard-large-{width}x{height}.png"
        path = assets / name
        assert path.is_file(), name
        assert _png_size(path) == (width, height)
        assert f"assets\\{name}" in image_directive
    for size in small:
        name = f"wizard-small-{size}.png"
        path = assets / name
        assert path.is_file(), name
        assert _png_size(path) == (size, size)
        assert f"assets\\{name}" in small_directive

    glow_hashes = []
    for index in range(16):
        name = f"glow-{index:02d}.png"
        path = assets / "glow" / name
        assert path.is_file(), name
        assert _png_size(path) == (192, 192)
        assert f'Source: "assets\\glow\\{name}"' in iss
        glow_hashes.append(path.read_bytes())
    assert glow_hashes[0] != glow_hashes[8]
    assert glow_hashes[0] != glow_hashes[15]
    assert (assets / "fonts" / "AnzuWizardSans-SemiBold.ttf").is_file()
    assert (assets / "fonts" / "OFL.txt").is_file()
