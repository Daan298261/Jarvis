from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.packs.manager import (
    export_pack,
    get_installed_pack,
    install_pack,
    list_installed_packs,
    mark_resource_user_modified,
    parse_manifest,
    preview_pack,
    rollback_pack,
    uninstall_pack,
    upgrade_pack,
)
from app.packs.store import reset_packs_store
from app.packs.trust import add_trusted_key, compute_signature

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "packs"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def pack_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.packs.store.data_dir", lambda: jarvis_env["tmp"])
    reset_packs_store()
    return jarvis_env["tmp"]


def test_pack_manifest_schema_validation():
    manifest = parse_manifest(_load_fixture("example-demo-v1.json"))
    assert manifest.schema_version == "1.0"
    assert manifest.id == "example.demo"
    assert manifest.version == "1.0.0"
    assert len(manifest.resources) == 3
    assert manifest.dependencies[0].id == "example.base"


def test_preview_install_requires_dependencies(pack_store):
    manifest = parse_manifest(_load_fixture("example-demo-v1.json"))
    preview = preview_pack(manifest, action="install")
    assert preview.valid is False
    assert "Missing required pack dependencies" in preview.errors[0]
    assert any(change.action == "create" for change in preview.changes)


def test_install_upgrade_conflict_rollback_uninstall(pack_store):
    base = parse_manifest(_load_fixture("example-base-v1.json"))
    v1 = parse_manifest(_load_fixture("example-demo-v1.json"))
    v2 = parse_manifest(_load_fixture("example-demo-v2.json"))

    install_pack(base)
    install_result = install_pack(v1)
    assert install_result["installation"]["version"] == "1.0.0"
    assert len(list_installed_packs()) == 2

    installed = get_installed_pack("example.demo")
    assert installed is not None
    assert len(installed["resources"]) == 3

    upgrade_preview = preview_pack(v2, action="upgrade")
    assert upgrade_preview.valid is True
    briefing_change = next(
        change for change in upgrade_preview.changes if change.resource_id.endswith("briefing")
    )
    assert briefing_change.action == "update"

    upgraded = upgrade_pack(v2)
    assert upgraded["installation"]["version"] == "1.1.0"
    assert upgraded["snapshot_id"]

    installed_after_upgrade = get_installed_pack("example.demo")
    goal = next(item for item in installed_after_upgrade["resources"] if item["resource_type"] == "goal")
    assert goal["data"]["priority"] == "high"
    assert "verified" in goal["data"]["title"]

    rolled_back = rollback_pack("example.demo")
    assert rolled_back["installation"]["version"] == "1.0.0"
    installed_after_rollback = get_installed_pack("example.demo")
    assert all(item["resource_type"] != "metric" for item in installed_after_rollback["resources"])

    uninstalled = uninstall_pack("example.demo")
    assert "example.demo.workflow.briefing" in uninstalled["removed_resources"]
    assert get_installed_pack("example.demo") is None


def test_user_modified_resource_skips_upgrade_until_override(pack_store):
    base = parse_manifest(_load_fixture("example-base-v1.json"))
    v1 = parse_manifest(_load_fixture("example-demo-v1.json"))
    v2 = parse_manifest(_load_fixture("example-demo-v2.json"))

    install_pack(base)
    install_pack(v1)
    mark_resource_user_modified(
        "example.demo.workflow.briefing",
        {
            "name": "Custom Briefing",
            "description": "User customized workflow",
            "category": "operations",
            "steps": [{"title": "Custom", "prompt": "User prompt"}],
        },
    )

    conflict_preview = preview_pack(v2, action="upgrade")
    briefing_change = next(
        change for change in conflict_preview.changes if change.resource_id.endswith("briefing")
    )
    assert briefing_change.action == "skip"
    assert briefing_change.reason == "user_modified"

    upgraded_without_override = upgrade_pack(v2)
    assert upgraded_without_override["installation"]["version"] == "1.1.0"
    installed_before_override = get_installed_pack("example.demo")
    briefing_before = next(
        item for item in installed_before_override["resources"] if item["resource_id"].endswith("briefing")
    )
    assert briefing_before["data"]["name"] == "Custom Briefing"

    override_preview = preview_pack(v2, action="upgrade", overrides={"example.demo.workflow.briefing": "use_pack"})
    briefing_override = next(
        change for change in override_preview.changes if change.resource_id.endswith("briefing")
    )
    assert briefing_override.action == "update"

    upgraded = upgrade_pack(v2, overrides={"example.demo.workflow.briefing": "use_pack"})
    installed = get_installed_pack("example.demo")
    briefing = next(item for item in installed["resources"] if item["resource_id"].endswith("briefing"))
    assert briefing["data"]["name"] == "Daily Briefing v2"


def test_export_strips_secrets(pack_store):
    base = parse_manifest(_load_fixture("example-base-v1.json"))
    demo = parse_manifest(_load_fixture("example-demo-v1.json"))
    install_pack(base)
    install_pack(demo)

    exported = export_pack("example.demo")
    integration = next(item for item in exported["resources"] if item["type"] == "integration")
    assert "api_key" not in integration["data"]
    assert integration["data"]["enabled"] is True


def test_signed_pack_trust_and_capability_policy(pack_store):
    manifest = parse_manifest(_load_fixture("example-demo-v1.json"))
    manifest.dependencies = []
    manifest.capabilities.required_tools = ["filesystem", "terminal", "nonexistent-tool"]
    add_trusted_key("publisher", "test-secret")
    manifest.trust.signer_key_id = "publisher"
    manifest.trust.trust_level = "verified"
    manifest.trust.signature = compute_signature(manifest, "test-secret")

    preview = preview_pack(manifest, action="install", require_signature=True)
    assert preview.trust["signature_valid"] is True
    assert preview.valid is False
    assert any("nonexistent-tool" in error for error in preview.errors)


def test_api_endpoints(pack_store, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.packs.store.data_dir", lambda: pack_store)
    client = TestClient(app)

    base_manifest = _load_fixture("example-base-v1.json")
    demo_manifest = _load_fixture("example-demo-v1.json")

    installed_base = client.post("/api/packs/install", json={"manifest": base_manifest})
    assert installed_base.status_code == 200

    preview = client.post(
        "/api/packs/preview",
        json={"manifest": demo_manifest, "action": "install"},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["valid"] is True
    assert len(body["changes"]) == 3

    installed = client.post("/api/packs/install", json={"manifest": demo_manifest})
    assert installed.status_code == 200

    listed = client.get("/api/packs")
    assert listed.status_code == 200
    assert len(listed.json()["packs"]) == 2

    detail = client.get("/api/packs/example.demo")
    assert detail.status_code == 200
    assert detail.json()["installation"]["version"] == "1.0.0"

    exported = client.post("/api/packs/export", json={"pack_id": "example.demo"})
    assert exported.status_code == 200
    assert exported.json()["id"] == "example.demo"

    removed = client.delete("/api/packs/example.demo")
    assert removed.status_code == 200
    assert removed.json()["pack_id"] == "example.demo"
