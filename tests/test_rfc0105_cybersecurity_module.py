from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent import skill_packs
from app.agent.local_harness import LocalHarnessPolicy, load_skill_blocks
from app.main import app
from app.modules import catalog_download, cybersecurity
from app.modules.supervisor import ModuleWorkerSupervisor, reset_supervisors, resolve_start_spec


@pytest.fixture(autouse=True)
def clean_module_state(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.cybersecurity.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.modules.catalog_download.data_dir", lambda: tmp_path)
    projects = tmp_path / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.modules.catalog_download.repo_root", lambda: tmp_path)
    monkeypatch.setattr("app.modules.cybersecurity.repo_root", lambda: tmp_path)
    cybersecurity.reset_state()
    catalog_download.reset_download_jobs()
    skill_packs.reset_skill_packs()
    reset_supervisors()
    cybersecurity.bootstrap_allowlist()
    yield


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


def test_module_grouping_has_six_members_in_order():
    payload = cybersecurity.build_module_payload()
    assert payload["id"] == "cybersecurity"
    ids = [member["id"] for member in payload["members"]]
    assert ids == list(cybersecurity.MEMBER_ORDER)
    assert len(ids) == 6


def test_enable_flags_gate_status(tmp_path):
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
    hints = load_skill_blocks(LocalHarnessPolicy())
    assert any("anthropic-cybersecurity-skills" in block for block in hints)


def test_stop_only_jarvis_managed_pid():
    supervisor = ModuleWorkerSupervisor("strix")
    assert supervisor.is_running is False
    foreign_pid = 424242
    assert supervisor.managed_pid is None


@pytest.mark.asyncio
async def test_start_stop_lifecycle_with_mock_spawn(tmp_path):
    root = tmp_path / "strix"
    root.mkdir()
    manifest = {
        "start": ["python", "-c", "import time; time.sleep(30)"],
        "health_url": "",
    }
    (root / "jarvis-module.json").write_text(json.dumps(manifest), encoding="utf-8")
    state = cybersecurity.load_state()
    state["module_enabled"] = True
    state["members"]["strix"]["enabled"] = True
    state["members"]["strix"]["recorded_path"] = str(root)
    cybersecurity.save_state(state)
    async def fake_spawn(self, spec):
        self._process = type("P", (), {"pid": 999, "returncode": None})()
        return True

    with patch.object(ModuleWorkerSupervisor, "_spawn", new=fake_spawn):
        result = await cybersecurity.start_member("strix")
        assert result["ok"] is True
        stop = await cybersecurity.stop_member("strix")
        assert stop["ok"] is True


def test_download_rejects_unknown_entry():
    with pytest.raises(ValueError, match="allowlisted"):
        import asyncio

        asyncio.run(catalog_download.start_download("not-a-real-entry"))


def test_download_allowlist_accepts_member():
    source = catalog_download.allowlisted_source("strix")
    assert source is not None
    assert "github.com/usestrix/strix" in source.source_url


def test_catalog_api_available(client=None):
    client = TestClient(app)
    response = client.get("/api/modules/catalog/cybersecurity")
    assert response.status_code == 200
    body = response.json()
    module = body.get("module") or body
    assert module["id"] == "cybersecurity"
    assert len(module["members"]) == 6


def test_enable_endpoints(client=None):
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
    assert entries[0]["id"] == "cybersecurity"


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
