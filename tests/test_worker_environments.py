from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workers import credentials as cred_broker
from app.workers.environments import (
    STATUS_CREATED,
    STATUS_RUNNING,
    STATUS_SUSPENDED,
    _load_registry,
    _registry_path,
    audit_log,
    browser_profile_dir,
    caches_dir,
    check_quota_violations,
    create_environment,
    delete_environment,
    environments_root,
    inspect_environment,
    list_audit_events,
    list_environments,
    logs_dir,
    reset_environment,
    resume_environment,
    revoke_environment_credential,
    start_environment,
    store_environment_credential,
    suspend_environment,
    workspace_dir,
    write_workspace_file,
)


@pytest.fixture
def env_root(jarvis_env, monkeypatch):
    root = jarvis_env["tmp"] / "worker-environments"
    monkeypatch.setattr("app.workers.environments.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.workers.credentials.data_dir", lambda: jarvis_env["tmp"])
    return root


def test_create_start_suspend_resume_lifecycle(env_root):
    created = create_environment(name="browser-worker", worker_kind="browser", agent_profile="research")
    env_id = created["id"]
    assert created["status"] == STATUS_CREATED
    assert created["name"] == "browser-worker"
    assert created["worker_kind"] == "browser"
    assert created["agent_profile"] == "research"
    assert workspace_dir(env_id).is_dir()
    assert caches_dir(env_id).is_dir()
    assert browser_profile_dir(env_id).is_dir()
    assert logs_dir(env_id).is_dir()

    started = start_environment(env_id)
    assert started["status"] == STATUS_RUNNING

    suspended = suspend_environment(env_id)
    assert suspended["status"] == STATUS_SUSPENDED
    assert suspended["suspended_at"]

    resumed = resume_environment(env_id)
    assert resumed["status"] == STATUS_RUNNING
    assert resumed["suspended_at"] is None


def test_reset_clears_workspace_but_keeps_identity(env_root):
    created = create_environment(name="code-worker", worker_kind="code")
    env_id = created["id"]
    start_environment(env_id)
    write_workspace_file(env_id, "main.py", "print('hello')")
    (caches_dir(env_id) / "pip.cache").write_text("cached", encoding="utf-8")

    reset = reset_environment(env_id)
    assert reset["status"] == STATUS_RUNNING
    assert not (workspace_dir(env_id) / "main.py").exists()
    assert not (caches_dir(env_id) / "pip.cache").exists()
    assert reset["id"] == env_id
    assert reset["name"] == "code-worker"


def test_delete_removes_workspace_and_credentials(env_root):
    created = create_environment(name="temp-worker")
    env_id = created["id"]
    write_workspace_file(env_id, "notes.txt", "keep me")
    store_environment_credential(
        env_id,
        capability="browser",
        label="session",
        secret="super-secret",
    )
    assert (environments_root() / env_id).exists()
    assert cred_broker._vault_path(env_id).exists()

    deleted = delete_environment(env_id)
    assert deleted["deleted"] is True
    assert deleted["id"] == env_id
    assert not (environments_root() / env_id).exists()
    assert not cred_broker._vault_path(env_id).exists()
    assert _load_registry() == []


def test_registry_survives_restart(env_root):
    created = create_environment(name="persistent", environment_id="env-persist-1")
    start_environment(created["id"])
    write_workspace_file(created["id"], "state.txt", "alive")

    reloaded = _load_registry()
    assert len(reloaded) == 1
    assert reloaded[0].id == "env-persist-1"
    assert (workspace_dir("env-persist-1") / "state.txt").read_text(encoding="utf-8") == "alive"
    assert _registry_path().exists()


def test_credentials_outside_workspace_and_revocable(env_root):
    created = create_environment(name="secure-worker")
    env_id = created["id"]
    cred = store_environment_credential(
        env_id,
        capability="web_fetch",
        label="api-key",
        secret="token-123",
    )
    vault = cred_broker._vault_path(env_id)
    assert vault.exists()
    assert vault.parent == cred_broker.credentials_root()
    assert not str(vault).startswith(str(workspace_dir(env_id)))

    inspect = inspect_environment(env_id)
    assert inspect["credentials"][0]["label"] == "api-key"
    assert "secret" not in inspect["credentials"][0]

    assert cred_broker.get_credential_secret(env_id, cred["id"]) == "token-123"
    revoked = revoke_environment_credential(env_id, cred["id"])
    assert revoked["revoked_at"]
    assert cred_broker.get_credential_secret(env_id, cred["id"]) is None


def test_quota_violation_blocks_start(env_root):
    created = create_environment(
        name="tiny-disk",
        quotas={"disk_mb": 0.0001},
    )
    env_id = created["id"]
    write_workspace_file(env_id, "big.txt", "x" * 2048)

    with pytest.raises(Exception, match="Quota exceeded"):
        start_environment(env_id)


def test_check_quota_violations_helper(env_root):
    created = create_environment(name="quota-check", quotas={"disk_mb": 1})
    env = _load_registry()[0]
    violations = check_quota_violations(env, usage={"disk_mb": 2})
    assert violations == ["disk_mb"]


def test_audit_log_records_lifecycle(env_root):
    created = create_environment(name="audited")
    env_id = created["id"]
    start_environment(env_id)
    store_environment_credential(env_id, capability="git", label="pat", secret="abc")
    cred_id = cred_broker.list_credentials(env_id)[0]["id"]
    revoke_environment_credential(env_id, cred_id)
    suspend_environment(env_id)
    resume_environment(env_id)
    reset_environment(env_id)
    delete_environment(env_id)

    events = list_audit_events()
    kinds = {row["event"] for row in events}
    assert "environment.created" in kinds
    assert "environment.started" in kinds
    assert "credential.stored" in kinds
    assert "credential.revoked" in kinds
    assert "environment.suspended" in kinds
    assert "environment.resumed" in kinds
    assert "environment.reset" in kinds
    assert "environment.deleted" in kinds


def test_api_endpoints(env_root):
    client = TestClient(app)

    created = client.post(
        "/api/worker-environments",
        json={"name": "api-worker", "worker_kind": "browser", "quotas": {"disk_mb": 512}},
    )
    assert created.status_code == 200
    body = created.json()
    env_id = body["id"]
    assert body["status"] == STATUS_CREATED

    listed = client.get("/api/worker-environments")
    assert listed.status_code == 200
    assert any(item["id"] == env_id for item in listed.json()["environments"])

    started = client.post(f"/api/worker-environments/{env_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == STATUS_RUNNING

    status = client.get(f"/api/worker-environments/{env_id}/status")
    assert status.status_code == 200
    assert status.json()["disk_usage_bytes"] >= 0
    assert status.json()["last_active_at"]

    inspect = client.get(f"/api/worker-environments/{env_id}")
    assert inspect.status_code == 200
    assert inspect.json()["workspace_path"]

    cred = client.post(
        f"/api/worker-environments/{env_id}/credentials",
        json={"capability": "browser", "label": "profile", "secret": "sekrit"},
    )
    assert cred.status_code == 200
    cred_id = cred.json()["id"]

    revoked = client.delete(f"/api/worker-environments/{env_id}/credentials/{cred_id}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]

    suspended = client.post(f"/api/worker-environments/{env_id}/suspend")
    assert suspended.status_code == 200
    assert suspended.json()["status"] == STATUS_SUSPENDED

    resumed = client.post(f"/api/worker-environments/{env_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == STATUS_RUNNING

    reset = client.post(f"/api/worker-environments/{env_id}/reset")
    assert reset.status_code == 200

    audit = client.get("/api/worker-environments/audit", params={"environment_id": env_id})
    assert audit.status_code == 200
    assert audit.json()["events"]

    deleted = client.delete(f"/api/worker-environments/{env_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = client.get(f"/api/worker-environments/{env_id}")
    assert missing.status_code == 404


def test_list_environments_returns_status_fields(env_root):
    create_environment(name="one")
    create_environment(name="two")
    rows = list_environments()
    assert len(rows) == 2
    for row in rows:
        assert "disk_usage_bytes" in row
        assert "last_active_at" in row


def test_manual_audit_entry_persists(env_root):
    entry = audit_log("environment.created", environment_id="manual", details={"name": "x"})
    assert entry["event"] == "environment.created"
    rows = list_audit_events(environment_id="manual")
    assert rows[-1]["environment_id"] == "manual"
