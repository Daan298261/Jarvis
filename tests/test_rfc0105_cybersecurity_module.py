from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent import skill_packs
from app.agent.local_harness import LocalHarnessPolicy, load_skill_blocks
from app.main import app
from app.modules import catalog_download, cybersecurity
from app.modules.supervisor import (
    ModuleWorkerSupervisor,
    is_loopback_url,
    reset_supervisors,
    resolve_start_spec,
)


@pytest.fixture(autouse=True)
def clean_module_state(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.cybersecurity.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.modules.catalog_download.data_dir", lambda: tmp_path)
    projects = tmp_path / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    (tmp_path / "le-gated").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Desktop" / "projects").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.modules.catalog_download.repo_root", lambda: tmp_path)
    monkeypatch.setattr("app.modules.cybersecurity.repo_root", lambda: tmp_path)
    monkeypatch.setattr("app.modules.supervisor.logs_dir", lambda: tmp_path / "logs")
    # Isolate EVERY discovery root so tests never see real Strix/checkouts.
    isolated_le = [tmp_path / "le-gated"]
    isolated_desktop = tmp_path / "Desktop" / "projects"
    isolated_library = tmp_path / "projects"
    for mod in ("app.modules.cybersecurity", "app.modules.catalog_download"):
        monkeypatch.setattr(f"{mod}.le_gated_roots", lambda roots=isolated_le: list(roots))
        monkeypatch.setattr(f"{mod}.desktop_projects_root", lambda p=isolated_desktop: p)
        monkeypatch.setattr(f"{mod}.library_projects_path", lambda p=isolated_library: p)
    cybersecurity.reset_state()
    catalog_download.reset_download_jobs()
    skill_packs.reset_skill_packs()
    reset_supervisors()
    cybersecurity.bootstrap_allowlist()
    yield
    # Ensure any leftover child workers are stopped between tests.
    async def _cleanup():
        for member_id in cybersecurity.MEMBER_ORDER:
            await cybersecurity.stop_member(member_id)

    try:
        asyncio.run(_cleanup())
    except Exception:
        pass
    reset_supervisors()


def test_discovery_prefers_recorded_path(tmp_path):
    recorded = tmp_path / "strix-checkout"
    recorded.mkdir()
    state = cybersecurity._default_state()
    state["members"]["strix"]["recorded_path"] = str(recorded)
    found = cybersecurity.discover_local_path("strix", state)
    assert found == recorded.resolve()


def test_discovery_finds_le_gated_slug(tmp_path, monkeypatch):
    root = tmp_path / "le-gated" / "strix"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.modules.cybersecurity.le_gated_roots",
        lambda: [tmp_path / "le-gated"],
    )
    found = cybersecurity.discover_local_path("strix")
    assert found == root.resolve()


def test_discovery_roots_order_includes_library_and_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.modules.cybersecurity.le_gated_roots",
        lambda: [tmp_path / "le-gated"],
    )
    monkeypatch.setattr(
        "app.modules.cybersecurity.desktop_projects_root",
        lambda: tmp_path / "Desktop" / "projects",
    )
    member = cybersecurity.MEMBERS["pentagi"]
    state = cybersecurity._default_state()
    candidates = [str(p) for p in cybersecurity._candidate_paths(member, state)]
    assert str(tmp_path / "le-gated" / "pentagi") in candidates
    assert str(tmp_path / "projects" / "pentagi") in candidates
    assert str(tmp_path / "Desktop" / "projects" / "pentagi") in candidates


def test_module_grouping_has_six_members_in_order():
    payload = cybersecurity.build_module_payload()
    assert payload["id"] == "cybersecurity"
    ids = [member["id"] for member in payload["members"]]
    assert ids == list(cybersecurity.MEMBER_ORDER)
    assert len(ids) == 6


def test_missing_clone_is_honest_missing(tmp_path):
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "strix")
    assert member["status"] == "missing"
    assert member["local_path"] is None
    assert member["connector"]["ready"] is False


@pytest.mark.asyncio
async def test_enable_flags_gate_skill_pack_register(tmp_path):
    checkout = tmp_path / "skills"
    skill_file = checkout / "alpha" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# skill", encoding="utf-8")
    state = cybersecurity.load_state()
    state["members"]["anthropic-cybersecurity-skills"]["recorded_path"] = str(checkout)
    state["members"]["anthropic-cybersecurity-skills"]["enabled"] = True
    state["module_enabled"] = True
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "anthropic-cybersecurity-skills")
    assert member["enabled"] is True
    assert member["status"] == "found"
    assert "alpha" in member.get("skill_pack_names", [])
    assert member["connector"]["registered"] is True
    # On-demand: empty policy/goal must NOT dump every pack into the prompt.
    cold = load_skill_blocks(LocalHarnessPolicy())
    assert not any("anthropic-cybersecurity-skills" in block for block in cold)
    # On-demand: goal or skill_ids must surface the pack names.
    hot = load_skill_blocks(
        LocalHarnessPolicy(skill_ids=["anthropic-cybersecurity-skills"]),
        goal="use cybersecurity skill pack",
    )
    assert any("anthropic-cybersecurity-skills" in block for block in hot)
    # Disable clears registration.
    await cybersecurity.set_member_enabled("anthropic-cybersecurity-skills", False)
    assert skill_packs.pack_names("cybersecurity", "anthropic-cybersecurity-skills") == []


def test_claude_red_skill_pack_same_shape(tmp_path):
    checkout = tmp_path / "claude-red"
    (checkout / "beta" / "SKILL.md").parent.mkdir(parents=True)
    (checkout / "beta" / "SKILL.md").write_text("# beta", encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["claude-red"]["enabled"] = True
    state["members"]["claude-red"]["recorded_path"] = str(checkout)
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "claude-red")
    assert "beta" in member["skill_pack_names"]
    assert member["connector"]["kind"] == "skill_pack"


def test_exploitarium_library_index_names_only(tmp_path):
    root = tmp_path / "exploitarium"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "alpha-title.md").write_text("BODY MUST NOT APPEAR\n" * 20, encoding="utf-8")
    (root / "notes" / "beta.txt").write_text("more body", encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["exploitarium"]["enabled"] = True
    state["members"]["exploitarium"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "exploitarium")
    assert member["library_index_count"] >= 2
    index = member["library_index"]
    assert all("name" in row and "title" in row for row in index)
    serialized = json.dumps(index)
    assert "BODY MUST NOT APPEAR" not in serialized
    # Retrieval helper respects enable flag
    assert len(cybersecurity.library_index_for("exploitarium")) >= 2


def test_flowsint_open_folder_when_no_ui(tmp_path):
    root = tmp_path / "flowsint"
    root.mkdir()
    (root / "README.md").write_text("ui elsewhere", encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["flowsint"]["enabled"] = True
    state["members"]["flowsint"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "flowsint")
    assert member["status"] == "found"
    assert member["connector_mode"] == "open_folder"
    assert member["ui_url"] is None
    assert member["connector"]["launchable"] is False


def test_flowsint_discovers_loopback_ui(tmp_path):
    root = tmp_path / "flowsint"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}}),
        encoding="utf-8",
    )
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["flowsint"]["enabled"] = True
    state["members"]["flowsint"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "flowsint")
    assert member["connector_mode"] == "loopback_ui"
    assert member["ui_url"] == "http://127.0.0.1:5174/"
    assert member["connector"]["launchable"] is True


def test_harness_entry_registers_cwd_when_enabled(tmp_path):
    root = tmp_path / "strix"
    root.mkdir()
    (root / "jarvis-module.json").write_text(
        json.dumps(
            {
                "start": [sys.executable, "-c", "import time; time.sleep(60)"],
                "health_url": "",
            }
        ),
        encoding="utf-8",
    )
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    state["members"]["strix"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    payload = cybersecurity.build_module_payload()
    member = next(m for m in payload["members"] if m["id"] == "strix")
    assert member["launchable"] is True
    assert member["harness_entry"]["cwd"] == str(root.resolve())
    entries = cybersecurity.harness_entries()
    assert any(e["member_id"] == "strix" and e["cwd"] == str(root.resolve()) for e in entries)


def test_stop_only_jarvis_managed_pid():
    supervisor = ModuleWorkerSupervisor("strix")
    assert supervisor.is_running is False
    assert supervisor.managed_pid is None
    # Foreign PIDs are never tracked — stop is a no-op when Jarvis did not start one.
    assert supervisor.managed_pid != 424242


def test_loopback_url_enforcement():
    assert is_loopback_url("") is True
    assert is_loopback_url("http://127.0.0.1:8080/health") is True
    assert is_loopback_url("http://localhost:5174/") is True
    assert is_loopback_url("http://0.0.0.0:8080/health") is False
    assert is_loopback_url("http://example.com/health") is False


def test_resolve_start_spec_rejects_non_loopback_health(tmp_path):
    root = tmp_path / "strix"
    root.mkdir()
    (root / "jarvis-module.json").write_text(
        json.dumps(
            {
                "start": ["python", "-c", "pass"],
                "health_url": "http://0.0.0.0:9999/health",
            }
        ),
        encoding="utf-8",
    )
    assert resolve_start_spec(root, "harness") is None


def test_resolve_start_spec_reads_manifest(tmp_path):
    root = tmp_path / "flowsint"
    root.mkdir()
    (root / "jarvis-module.json").write_text(
        json.dumps({"start": ["npm", "run", "dev"], "health_url": "http://127.0.0.1:5174/"}),
        encoding="utf-8",
    )
    spec = resolve_start_spec(root, "graph_ui")
    assert spec is not None
    assert spec.argv[0] == "npm"
    assert spec.env.get("HOST") == "127.0.0.1"
    assert "127.0.0.1" in spec.health_url


def test_resolve_start_spec_missing_metadata_is_none(tmp_path):
    root = tmp_path / "empty-clone"
    root.mkdir()
    (root / "README.md").write_text("no start", encoding="utf-8")
    assert resolve_start_spec(root, "harness") is None
    assert resolve_start_spec(root, "graph_ui") is None


@pytest.mark.asyncio
async def test_start_without_path_fails_closed():
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    cybersecurity.save_state(state)
    result = await cybersecurity.start_member("strix")
    assert result["ok"] is False
    assert result.get("status") == "missing"
    assert "not found" in result["detail"].lower()


@pytest.mark.asyncio
async def test_start_without_metadata_fails_closed(tmp_path):
    root = tmp_path / "strix"
    root.mkdir()
    (root / "README.md").write_text("no launcher", encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    state["members"]["strix"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    result = await cybersecurity.start_member("strix")
    assert result["ok"] is False
    assert "start metadata" in result["detail"].lower()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_loopback_worker(root: Path, port: int) -> None:
    """Checkout-local loopback HTTP worker used by start/stop proofs (no exploit content)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.py").write_text(
        "\n".join(
            [
                "from http.server import BaseHTTPRequestHandler, HTTPServer",
                f"PORT = {port}",
                "class Handler(BaseHTTPRequestHandler):",
                "    def do_GET(self):",
                "        self.send_response(200)",
                "        self.end_headers()",
                "        self.wfile.write(b'ok')",
                "    def log_message(self, *args):",
                "        return",
                "HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "jarvis-module.json").write_text(
        json.dumps(
            {
                "start": [sys.executable, "server.py"],
                "health_url": f"http://127.0.0.1:{port}/",
                "env": {"PORT": str(port)},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_real_start_stop_loopback_bind(tmp_path):
    """Prove start/stop owns a real loopback child — not a mock décor path."""
    from app.modules.supervisor import get_supervisor

    root = tmp_path / "strix"
    port = _free_loopback_port()
    _write_loopback_worker(root, port)
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    state["members"]["strix"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)

    started = await cybersecurity.start_member("strix")
    assert started["ok"] is True, started
    assert started["pid"] is not None
    assert started["health_url"].startswith("http://127.0.0.1:")
    managed = get_supervisor("strix")
    assert managed.is_running is True
    assert managed.managed_pid == started["pid"]

    stopped = await cybersecurity.stop_member("strix")
    assert stopped["ok"] is True
    assert managed.is_running is False
    assert managed.managed_pid is None


@pytest.mark.asyncio
async def test_disable_awaits_stop_of_jarvis_pid(tmp_path):
    from app.modules.supervisor import get_supervisor

    root = tmp_path / "pentagi"
    port = _free_loopback_port()
    _write_loopback_worker(root, port)
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["pentagi"]["enabled"] = True
    state["members"]["pentagi"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    started = await cybersecurity.start_member("pentagi")
    assert started["ok"] is True, started
    assert get_supervisor("pentagi").is_running is True
    await cybersecurity.set_member_enabled("pentagi", False)
    assert get_supervisor("pentagi").is_running is False


def test_download_rejects_unknown_entry():
    with pytest.raises(ValueError, match="allowlisted"):
        asyncio.run(catalog_download.start_download("not-a-real-entry"))


def test_download_allowlist_accepts_member():
    source = catalog_download.allowlisted_source("strix")
    assert source is not None
    assert "github.com/usestrix/strix" in source.source_url
    for member_id in cybersecurity.MEMBER_ORDER:
        assert catalog_download.allowlisted_source(member_id) is not None


def test_catalog_zip_and_clone_honor_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    def boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("must not fetch when internet is denied")

    monkeypatch.setattr("app.modules.catalog_download.subprocess.run", boom)
    dest = tmp_path / "mod"
    with pytest.raises(PermissionError):
        catalog_download._run_git_clone("https://github.com/usestrix/strix", dest)
    with pytest.raises(PermissionError):
        catalog_download._run_zip_download("https://github.com/usestrix/strix", dest)
    assert ran["n"] == 0


def test_catalog_api_available(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    client = TestClient(app)
    response = client.get("/api/modules/catalog/cybersecurity")
    assert response.status_code == 200
    body = response.json()
    module = body.get("module") or body
    assert module["id"] == "cybersecurity"
    assert len(module["members"]) == 6


def test_enable_endpoints(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    client = TestClient(app)
    off = client.post("/api/modules/catalog/cybersecurity/enable", json={"enabled": True})
    assert off.status_code == 200
    tool = client.post(
        "/api/modules/catalog/cybersecurity/tools/strix/enable",
        json={"enabled": True},
    )
    assert tool.status_code == 200
    listed = client.get("/api/modules/catalog")
    assert listed.status_code == 200
    entries = listed.json()["entries"]
    cyber = next(e for e in entries if e["id"] == "cybersecurity")
    assert cyber["integrate_decision"] == "partial"
    assert cyber.get("connector_depth") == "launch_hooks"


def test_start_api_fails_closed_without_checkout(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    client = TestClient(app)
    client.post("/api/modules/catalog/cybersecurity/enable", json={"enabled": True})
    client.post("/api/modules/catalog/cybersecurity/tools/strix/enable", json={"enabled": True})
    response = client.post("/api/modules/catalog/cybersecurity/tools/strix/start")
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_skill_pack_start_fails_closed(jarvis_env, monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.auth.load_settings", lambda: jarvis_env["settings"])
    checkout = tmp_path / "skills"
    checkout.mkdir()
    (checkout / "x" / "SKILL.md").parent.mkdir(parents=True)
    (checkout / "x" / "SKILL.md").write_text("# x", encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["anthropic-cybersecurity-skills"]["enabled"] = True
    state["members"]["anthropic-cybersecurity-skills"]["recorded_path"] = str(checkout)
    cybersecurity.save_state(state)
    client = TestClient(app)
    response = client.post(
        "/api/modules/catalog/cybersecurity/tools/anthropic-cybersecurity-skills/start"
    )
    assert response.status_code == 400


def test_dest_extra_uses_usb_jarvis_projects(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    extra.mkdir()
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    root = catalog_download._dest_root("extra")
    assert root == extra / "Jarvis" / "projects"
    assert root.is_dir()


def test_dest_path_clones_into_allowed_usb_folder(tmp_path, monkeypatch):
    extra = tmp_path / "USB" / "tools"
    extra.mkdir(parents=True)
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(tmp_path)],
    )
    root = catalog_download._dest_root("library", dest_path=str(extra))
    assert root.resolve() == extra.resolve()


def test_dest_path_outside_workspace_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    allowed = tmp_path / "inside"
    allowed.mkdir()
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(allowed)],
    )
    with pytest.raises(PermissionError):
        catalog_download._dest_root("library", dest_path=str(outside))
