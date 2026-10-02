from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import LOCAL_NETWORK_SCOPE, default_allowed_directories
from app.policy.computer_permissions import (
    apply_grant, evaluate_permission, evaluate_tool_permissions,
    permission_ids_for_tool, reset_computer_permission_state,
)
from app.tools.safety import _private_lan_unc, resolve_allowed_path


def test_private_unc_host_classification():
    assert _private_lan_unc(r"\\nas.local\share\game.exe")
    assert _private_lan_unc(r"\\nas.lan\share\game.exe")
    assert _private_lan_unc(r"\\192.168.1.12\media\game.exe")
    assert _private_lan_unc(r"\\nas\media\game.exe")
    assert _private_lan_unc(r"\\wsl.localhost\Ubuntu\home\taco\notes.md")
    assert _private_lan_unc(r"\\wsl$\Ubuntu\home\taco\notes.md")
    assert _private_lan_unc(r"\\host.docker.internal\share\app.exe")
    assert _private_lan_unc(r"\\localhost\c$\Windows")
    assert not _private_lan_unc(r"\\8.8.8.8\share\game.exe")
    assert not _private_lan_unc(r"\\public.example.com\share\game.exe")
    assert not _private_lan_unc(r"\\files.example.com\share\game.exe")


def test_wsl_localhost_unc_resolves_under_lan_scope():
    allowed = [LOCAL_NETWORK_SCOPE]
    resolved = resolve_allowed_path(r"\\wsl.localhost\Ubuntu\home\taco\notes.md", allowed)
    text = str(resolved).replace("/", "\\").lower()
    assert "wsl.localhost" in text
    assert "notes.md" in text
    docker = resolve_allowed_path(r"\\host.docker.internal\projects\app", allowed)
    assert "host.docker.internal" in str(docker).replace("/", "\\").lower()
    with pytest.raises(PermissionError):
        resolve_allowed_path(r"\\wsl.localhost\Ubuntu\home", [str(Path.home())])


def test_wsl_localhost_browse_is_local_network_not_internet():
    assert permission_ids_for_tool("browser", {"url": "http://wsl.localhost:3000/"}) == ["network.local"]
    assert permission_ids_for_tool("web_fetch", {"url": "http://wsl.localhost:8080/health"}) == ["network.local"]
    assert permission_ids_for_tool(
        "browser_use",
        {"goal": "open the Vite app at http://wsl.localhost:5173"},
    ) == ["network.local"]
    assert permission_ids_for_tool("browser", {"url": "http://host.docker.internal:8080"}) == ["network.local"]
    assert permission_ids_for_tool("web_fetch", {"url": "https://example.com"}) == ["network.internet"]


def test_owner_scope_covers_steam_and_local_shares(tmp_path):
    allowed = default_allowed_directories()
    assert LOCAL_NETWORK_SCOPE in allowed
    if os.name != "nt":
        share = r"\\nas.local\games\steam.exe"
        assert "nas.local" in str(resolve_allowed_path(share, allowed)).lower()
        with pytest.raises(PermissionError):
            resolve_allowed_path(r"\\8.8.8.8\share\game.exe", allowed)
        return
    steam = Path(Path.home().anchor) / "Program Files (x86)" / "Steam" / "steam.exe"
    assert resolve_allowed_path(str(steam), allowed) == steam.resolve()
    share = r"\\nas.local\games\steam.exe"
    assert str(resolve_allowed_path(share, allowed)).lower() == share.lower()
    with pytest.raises(PermissionError):
        resolve_allowed_path(r"\\8.8.8.8\share\game.exe", allowed)
    with pytest.raises(PermissionError):
        resolve_allowed_path(share, [str(tmp_path)])
    with pytest.raises(PermissionError):
        resolve_allowed_path(str(steam), [str(tmp_path)])


def test_upgraded_install_with_old_workspace_list_gains_every_drive(monkeypatch):
    """1.4.12 installs saved only profile folders; loading settings must widen to all drives."""
    from app.config import sanitize_allowed_directories

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    old = [str(Path.home() / "Desktop"), str(Path.home() / "Documents")]
    widened = sanitize_allowed_directories(old)
    assert widened[:2] == old
    for root in default_allowed_directories():
        assert root in widened
    if os.name == "nt":
        public = Path(Path.home().anchor) / "Users" / "Public" / "Desktop"
        assert resolve_allowed_path(str(public), widened) == public.resolve()


def test_local_network_default_is_allowed_but_explicit_deny_wins(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    assert evaluate_permission("network.local").status == "allow"
    assert evaluate_tool_permissions("web_fetch", {"url": "http://nas.local/status"}).status == "allow"
    assert evaluate_tool_permissions("web_fetch", {"url": "http://nas/status"}).status == "allow"
    assert evaluate_permission("network.internet").status == "allow"
    assert evaluate_tool_permissions("hexstrike_defensive", {"action": "lan_inventory"}).status == "allow"
    assert evaluate_tool_permissions("filesystem", {"path": r"\\nas.local\share\x"}).status == "allow"
    # A WAN URL that merely mentions a LAN name is still internet use.
    assert permission_ids_for_tool("web_fetch", {"url": "https://example.com/?next=nas.local"}) == ["network.internet"]
    apply_grant("network.local", "deny")
    assert evaluate_permission("network.local").status == "deny"
    assert evaluate_tool_permissions("filesystem", {"path": r"\\nas.local\share\x"}).status == "deny"


def test_browser_use_goal_with_lan_host_is_local_network():
    assert permission_ids_for_tool(
        "browser_use",
        {"goal": "open the NAS status page at http://nas.local/status"},
    ) == ["network.local"]
    assert permission_ids_for_tool(
        "browser_use",
        {"goal": "search publicly for router firmware"},
    ) == ["network.internet"]
    assert permission_ids_for_tool(
        "browser_use",
        {"goal": "follow https://example.com/?next=nas.local"},
    ) == ["network.internet"]


def test_browser_follow_on_actions_keep_local_network_permission():
    from app.tools.browser import browser_permission_url

    assert browser_permission_url("open", {"url": "http://nas.local/status"}) == "http://nas.local/status"
    assert browser_permission_url("snapshot", {}, "http://nas.local/status") == "http://nas.local/status"
    assert permission_ids_for_tool(
        "browser",
        {"url": browser_permission_url("snapshot", {}, "http://nas.local/status"), "action": "snapshot"},
    ) == ["network.local"]
    assert permission_ids_for_tool(
        "browser",
        {"url": browser_permission_url("snapshot", {}, "https://example.com/"), "action": "snapshot"},
    ) == ["network.internet"]


def test_hexstrike_operator_lan_inventory_is_local_network_only():
    assert permission_ids_for_tool(
        "hexstrike_operator",
        {"operation": "operate", "capability_id": "defensive:lan_inventory"},
    ) == ["network.local"]
    assert permission_ids_for_tool(
        "hexstrike_operator",
        {"operation": "start"},
    ) == ["cyber.hexstrike"]


def test_apply_settings_unions_newly_mounted_drives(monkeypatch, tmp_path):
    from app.config import AppSettings
    from app.tools.registry import ToolRegistry

    first = tmp_path / "vol-a"
    second = tmp_path / "vol-b"
    first.mkdir()
    second.mkdir()
    roots = {"now": [str(first)]}
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: list(roots["now"]))
    registry = ToolRegistry()
    settings = AppSettings(allowed_directories=[str(first)])
    registry.apply_settings(settings)
    assert str(first) in registry._context["allowed_directories"]
    assert str(second) not in registry._context["allowed_directories"]
    roots["now"] = [str(first), str(second)]
    registry.apply_settings(settings)
    assert str(second) in registry._context["allowed_directories"]


def test_live_context_unions_drive_without_settings_save(monkeypatch, tmp_path):
    from app.config import AppSettings
    from app.tools.registry import ToolRegistry

    first = tmp_path / "vol-a"
    second = tmp_path / "vol-b"
    first.mkdir()
    second.mkdir()
    roots = {"now": [str(first)]}
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: list(roots["now"]))
    registry = ToolRegistry()
    settings = AppSettings(allowed_directories=[str(first)])
    registry.apply_settings(settings)
    roots["now"] = [str(first), str(second)]
    live = registry._live_context()
    assert str(second) in live["allowed_directories"]
    assert str(second) in registry._context["allowed_directories"]


def test_lta_and_hexstrike_accept_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.config import live_allowed_directories
    from app.security.hexstrike_defensive import normalize_scope
    from app.security.hexstrike_operator import artifact_path_allowed
    from app.security.lta_archive import assert_path_allowed
    from app.security.target_registry import normalize_target

    home = tmp_path / "home"
    extra = tmp_path / "E"
    home.mkdir()
    extra.mkdir()
    manifest = extra / "manifest.xml"
    manifest.write_text("<LTA/>", encoding="utf-8")
    evidence = extra / "evidence.bin"
    evidence.write_bytes(b"x")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: [str(home), str(extra)])
    saved = [str(home)]
    stale = SimpleNamespace(allowed_directories=saved)
    monkeypatch.setattr("app.security.lta_archive.load_settings", lambda: stale)
    monkeypatch.setattr("app.security.hexstrike_defensive.load_settings", lambda: stale)
    monkeypatch.setattr("app.security.hexstrike_operator.load_settings", lambda: stale)
    monkeypatch.setattr("app.security.target_registry.load_settings", lambda: stale)
    roots = live_allowed_directories(saved)
    assert str(extra) in roots
    assert assert_path_allowed(str(manifest)).resolve() == manifest.resolve()
    assert Path(normalize_scope("local_path", str(extra))).resolve() == extra.resolve()
    assert artifact_path_allowed(evidence)
    assert Path(normalize_target("local_path", str(extra))).resolve() == extra.resolve()
    from app.config import AppSettings, live_workspace_roots_from_context

    assert str(extra) in live_workspace_roots_from_context({"allowed_directories": saved})
    assert str(extra) in live_workspace_roots_from_context(AppSettings(allowed_directories=saved))
    assert live_workspace_roots_from_context({}) == []


def test_extra_volume_roots_expand_media_and_skip_os_volume(monkeypatch, tmp_path):
    from app import config

    media = tmp_path / "media"
    usb = media / "owner" / "USBDRIVE"
    usb.mkdir(parents=True)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(config, "_posix_owner_roots", lambda: [Path("/"), media])
    monkeypatch.setattr(config, "os_volume_root", lambda: Path("/"))
    roots = {path.resolve() for path in config.extra_volume_roots()}
    assert usb.resolve() in roots
    assert Path("/") not in roots
    assert media.resolve() not in roots


def test_environment_block_lists_live_extra_volume(monkeypatch, tmp_path):
    from app.agent.loop import _environment_block
    from app.config import AppSettings

    extra = tmp_path / "E"
    extra.mkdir()
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(tmp_path), str(extra)],
    )
    text = _environment_block(AppSettings(allowed_directories=[str(tmp_path)]))
    assert str(extra) in text


@pytest.mark.asyncio
async def test_get_settings_unions_plugged_in_drive_without_save(monkeypatch, tmp_path):
    from app.api.settings import get_settings
    from app.config import AppSettings

    home = tmp_path / "home"
    extra = tmp_path / "E"
    home.mkdir()
    extra.mkdir()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: [str(home), str(extra)])
    monkeypatch.setattr(
        "app.api.settings.load_settings",
        lambda: AppSettings(allowed_directories=[str(home)]),
    )
    payload = await get_settings()
    assert str(home) in payload["allowed_directories"]
    assert str(extra) in payload["allowed_directories"]


@pytest.mark.asyncio
async def test_system_info_unions_plugged_in_drive_without_save(monkeypatch, tmp_path):
    from app.api.system import system_info
    from app.config import AppSettings

    home = tmp_path / "home"
    extra = tmp_path / "E"
    home.mkdir()
    extra.mkdir()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: [str(home), str(extra)])
    monkeypatch.setattr(
        "app.api.system.load_settings",
        lambda: AppSettings(allowed_directories=[str(home)]),
    )

    async def fake_snapshot(_settings):
        return {"loaded": False, "loading": False, "active_model": "", "last_error": ""}

    monkeypatch.setattr("app.api.system.MANAGER.snapshot", fake_snapshot)
    monkeypatch.setattr("app.api.system.hardware_dict", lambda: {})
    monkeypatch.setattr("app.api.system.capability_snapshot", lambda: {})
    monkeypatch.setattr("app.api.system.jarvis_mcp_manifest", lambda: {})
    monkeypatch.setattr("app.api.system.acp_status", lambda: {})

    async def fake_swarm():
        return {}

    monkeypatch.setattr("app.api.system.swarm_snapshot", fake_swarm)
    payload = await system_info()
    assert str(home) in payload["allowed_directories"]
    assert str(extra) in payload["allowed_directories"]


def _stale_usb_context(monkeypatch, tmp_path):
    """Saved allowlist is only home; extra is a sibling volume that just appeared."""
    home = tmp_path / "home"
    extra = tmp_path / "E"
    home.mkdir()
    extra.mkdir()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: [str(home), str(extra)])
    return home, extra, {"allowed_directories": [str(home)]}


async def test_filesystem_writes_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    from app.tools.filesystem import FilesystemTool

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    dest = extra / "Notes"
    dest.mkdir()
    tool = FilesystemTool(lambda: stale)
    result = await tool.execute(action="write", path=str(dest), content="on-usb", create_backup=False)
    assert result.success, result.error
    assert (dest / "note.txt").read_text(encoding="utf-8") == "on-usb"


async def test_git_status_on_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    import subprocess

    from app.tools.git_tools import GitTool

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    repo = extra / "proj"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "jarvis@example.test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=repo, check=True, capture_output=True)
    (repo / "readme.txt").write_text("usb\n", encoding="utf-8")
    subprocess.run(["git", "add", "readme.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    tool = GitTool(lambda: stale)
    result = await tool.execute(action="status", path=str(repo))
    assert result.success, result.error


async def test_python_and_terminal_use_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    from app.tools.python_exec import PythonTool
    from app.tools.terminal import TerminalTool

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    script = extra / "hello.py"
    script.write_text("print('from-usb')\n", encoding="utf-8")
    (extra / "here.txt").write_text("ok", encoding="utf-8")
    py = PythonTool(lambda: stale)
    ran = await py.execute(action="run_file", path=str(script))
    assert ran.success, ran.error
    assert "from-usb" in ran.output
    sh = TerminalTool(lambda: stale)
    listed = await sh.execute(command="cat here.txt", shell="bash", working_directory=str(extra))
    assert listed.success, listed.error
    assert "ok" in listed.output


async def test_office_docker_screenshot_desktop_dcc_use_plugged_in_drive(monkeypatch, tmp_path):
    from app.tools.dcc_tools import _allowed as dcc_allowed
    from app.tools.dcc_tools import _resolve as dcc_resolve
    from app.tools.desktop import DesktopTool
    from app.tools.docker_tools import DockerTool
    from app.tools.office import OfficeTool
    from app.tools.screenshot import ScreenshotTool, screenshot_dest
    from app.tools.safety import resolve_allowed_path

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    sheets = extra / "Sheets"
    sheets.mkdir()
    office = OfficeTool(lambda: stale)
    created = await office.execute(
        app="excel",
        action="create",
        path=str(sheets),
        content="a\tb\n1\t2",
        backend="library",
    )
    assert created.success, created.error
    dest = sheets / "Jarvis-excel.xlsx"
    assert dest.exists()

    docker = DockerTool(lambda: stale)
    (extra / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert Path(docker._build_path(str(extra))).resolve() == extra.resolve()

    shot = ScreenshotTool(lambda: stale)
    assert str(extra) in shot._allowed()
    image = extra / "screen.png"
    image.write_bytes(b"png")
    described = await shot.execute(action="describe_path", path=str(image))
    assert described.success, described.error
    capture_dest = screenshot_dest(str(extra), allowed=shot._allowed())
    assert capture_dest.parent == extra

    desktop = DesktopTool(lambda: stale)
    assert str(extra) in desktop._allowed()
    assert resolve_allowed_path(str(extra), desktop._allowed()).resolve() == extra.resolve()

    assert str(extra) in dcc_allowed(stale)
    blend = extra / "widget.blend"
    blend.write_bytes(b"x")
    assert dcc_resolve(str(blend), dcc_allowed(stale)).resolve() == blend.resolve()


def test_desktop_browser_use_screenshot_without_getter_union_extra_drive(monkeypatch, tmp_path):
    from app.config import AppSettings, live_tool_workspace_roots
    from app.tools.browser_use import BrowserUseTool
    from app.tools.desktop import DesktopTool
    from app.tools.screenshot import ScreenshotTool

    home, extra, _stale = _stale_usb_context(monkeypatch, tmp_path)
    monkeypatch.setattr("app.config.load_settings", lambda: AppSettings(allowed_directories=[str(home)]))
    assert str(extra) in live_tool_workspace_roots({})
    assert live_tool_workspace_roots({}) != []
    assert str(extra) in DesktopTool()._allowed()
    assert str(extra) in BrowserUseTool()._allowed()
    assert str(extra) in ScreenshotTool()._allowed()


@pytest.mark.asyncio
async def test_external_ingest_browser_use_sees_plugged_in_drive(monkeypatch, tmp_path):
    from app.tools.external_ingest import ExternalIngestTool

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    seen: dict[str, list[str]] = {}

    async def fake_ingest(url, **kwargs):
        seen["allowed"] = list(kwargs["browser_use_tool"]._allowed())
        return {"title": "ok", "url": url}

    monkeypatch.setattr("app.ingest.orchestrator.ingest_url", fake_ingest)
    tool = ExternalIngestTool(lambda: stale)
    result = await tool.execute(url="https://example.com/post")
    assert result.success, result.error
    assert str(extra) in seen["allowed"]


async def test_verify_and_workers_use_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    import subprocess

    from app.tools.base import ToolResult
    from app.tools.code_worker import CodeWorkerTool
    from app.tools.interpreter import OpenInterpreterTool
    from app.tools.verify_code import VerifyCodeTool

    _home, extra, stale = _stale_usb_context(monkeypatch, tmp_path)
    repo = extra / "code"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "jarvis@example.test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=repo, check=True, capture_output=True)
    (repo / "readme.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "readme.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    verify = VerifyCodeTool(lambda: stale)
    checked = await verify.execute(path=str(repo), run_tests=False)
    assert checked.success, checked.error
    assert checked.data.get("ok") is True

    seen: list[Path] = []

    async def fake_run(goal, path, settings):
        seen.append(Path(path).resolve())
        return ToolResult(True, f"ok {path}", data={"path": str(path)})

    monkeypatch.setattr("app.tools.code_worker._BACKEND.run", fake_run)
    monkeypatch.setattr("app.tools.interpreter._BACKEND.run", fake_run)
    worker = CodeWorkerTool(lambda: stale)
    delegated = await worker.execute(action="delegate", goal="fix tests", path=str(repo))
    assert delegated.success, delegated.error
    assert seen[-1] == repo.resolve()
    interp = OpenInterpreterTool(lambda: stale)
    interpreted = await interp.execute(action="delegate", goal="fix tests", path=str(repo))
    assert interpreted.success, interpreted.error
    assert seen[-1] == repo.resolve()
