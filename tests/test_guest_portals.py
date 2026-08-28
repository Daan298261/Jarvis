from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.guests.service import SERVICE
from app.guests.store import reset_guest_store
from app.main import app


def _owner_settings(tmp_path: str, test_key: str) -> AppSettings:
    return AppSettings(
        allowed_directories=[tmp_path],
        auth_required=True,
        auth_token=test_key,
    )


def _owner_client(monkeypatch, settings: AppSettings) -> TestClient:
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    return TestClient(app)


def _create_portal(client: TestClient, owner_key: str, **overrides):
    body = {
        "label": "Client review",
        "guest_label": "client-a",
        "grants": [
            {
                "resource_type": "task",
                "resource_id": "task-allowed",
                "actions": ["read", "query", "approve"],
            }
        ],
        "limits": {"single_use": False, "max_sessions": 2, "max_uses": None},
    }
    body.update(overrides)
    return client.post(
        "/api/guest-portals",
        headers={"X-Jarvis-Key": owner_key},
        json=body,
    )


@pytest.fixture
def portal_env(jarvis_env, monkeypatch):
    reset_guest_store()
    test_key = "jarvis_pk_guest_portal_owner"
    settings = _owner_settings(str(jarvis_env["tmp"]), test_key)
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    client = _owner_client(monkeypatch, settings)
    yield {"client": client, "owner_key": test_key, "tmp": jarvis_env["tmp"]}
    reset_guest_store()


def test_preview_effective_permissions_before_issuing(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    res = client.post(
        "/api/guest-portals/preview",
        headers={"X-Jarvis-Key": owner_key},
        json={
            "grants": [
                {
                    "resource_type": "task",
                    "resource_id": "task-1",
                    "actions": ["read"],
                }
            ],
            "limits": {"single_use": False},
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert "filesystem" in payload["denied_capabilities"]
    assert payload["allowed_actions_summary"]["task:task-1"] == ["read"]


def test_scope_isolation_for_guest_tasks(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    created = _create_portal(client, owner_key)
    assert created.status_code == 200
    token = created.json()["token"]

    guest_headers = {"Authorization": f"Bearer {token}"}
    session = client.post("/api/guest/session", headers=guest_headers)
    assert session.status_code == 200
    session_id = session.json()["session_id"]
    guest_headers["X-Jarvis-Guest-Session"] = session_id

    allowed = client.get("/api/guest/tasks/task-allowed", headers=guest_headers)
    assert allowed.status_code in {200, 404}

    denied = client.get("/api/guest/tasks/other-task", headers=guest_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "scope_denied"

    owner_blocked = client.get("/api/guest/tasks/task-allowed")
    assert owner_blocked.status_code == 401


def test_expired_portal_token_rejected(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()

    created = _create_portal(client, owner_key, expires_at=past)
    token = created.json()["token"]

    res = client.post("/api/guest/session", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "portal_expired"


def test_owner_can_revoke_portal_immediately(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    created = _create_portal(client, owner_key)
    portal_id = created.json()["id"]
    token = created.json()["token"]

    revoke = client.post(f"/api/guest-portals/{portal_id}/revoke", headers={"X-Jarvis-Key": owner_key})
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    res = client.post("/api/guest/session", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "portal_revoked"


def test_single_use_token_revoked_after_authorized_action(portal_env, monkeypatch):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    created = client.post(
        "/api/guest-portals",
        headers={"X-Jarvis-Key": owner_key},
        json={
            "label": "One shot",
            "guest_label": "guest-one",
            "grants": [
                {
                    "resource_type": "task",
                    "resource_id": "task-allowed",
                    "actions": ["read"],
                }
            ],
            "limits": {"single_use": True},
        },
    )
    token = created.json()["token"]
    portal_id = created.json()["id"]
    guest_headers = {"Authorization": f"Bearer {token}"}

    session = client.post("/api/guest/session", headers=guest_headers)
    guest_headers["X-Jarvis-Guest-Session"] = session.json()["session_id"]

    first = client.get("/api/guest/tasks/task-allowed", headers=guest_headers)
    assert first.status_code in {200, 404}

    portal = SERVICE.get_portal(portal_id)
    assert portal is not None
    assert portal.revoked is True

    second = client.post("/api/guest/session", headers=guest_headers)
    assert second.status_code == 403


def test_guest_actions_are_audited(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    created = _create_portal(client, owner_key)
    portal_id = created.json()["id"]
    token = created.json()["token"]
    guest_headers = {"Authorization": f"Bearer {token}"}

    session = client.post("/api/guest/session", headers=guest_headers)
    guest_headers["X-Jarvis-Guest-Session"] = session.json()["session_id"]
    client.get("/api/guest/tasks/other-task", headers=guest_headers)

    audit = client.get(f"/api/guest-portals/{portal_id}/audit", headers={"X-Jarvis-Key": owner_key})
    assert audit.status_code == 200
    rows = audit.json()
    assert any(row["action"] == "session.start" and row["outcome"] == "ok" for row in rows)
    assert any(row["action"] == "task.read" and row["outcome"] == "denied" for row in rows)
    assert all(row.get("guest_label") == "client-a" for row in rows if row["action"] != "portal.create")


def test_guest_cannot_access_owner_settings(portal_env):
    client = portal_env["client"]
    owner_key = portal_env["owner_key"]

    created = _create_portal(client, owner_key)
    token = created.json()["token"]
    guest_headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/settings", headers=guest_headers)
    assert res.status_code == 401
