from __future__ import annotations

import json

import pytest

from app.inference.runtime_profiles import get_runtime_profile, reset_runtime_profiles
from app.inference.security_gates import (
    authorized_runtime_profiles,
    get_gate_status,
    lock_gate,
    security_gates_path,
    set_gate_password,
    unlock_gate,
)


@pytest.fixture
def security_gate_store(jarvis_env, monkeypatch):
    root = jarvis_env["tmp"]
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: root)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: root)
    reset_runtime_profiles()
    return root


def test_password_gate_hashes_password_and_persists_enabled_state(security_gate_store):
    password = "correct horse battery staple"
    status = set_gate_password("blue-team", new_password=password, enable=False)
    assert status.configured is True
    assert status.enabled is False

    payload = security_gates_path().read_text(encoding="utf-8")
    assert password not in payload
    parsed = json.loads(payload)
    assert parsed["roles"]["blue-team"]["kdf"] == "scrypt"

    unlocked = unlock_gate("blue", password)
    assert unlocked.enabled is True
    assert get_gate_status("soc").enabled is True

    # Persistence is file-backed; a fresh read sees the same enabled state.
    assert json.loads(security_gates_path().read_text(encoding="utf-8"))["roles"]["blue-team"]["enabled"] is True

    locked = lock_gate("blue-team")
    assert locked.enabled is False
    assert get_gate_status("blue-team").enabled is False


def test_gate_rejects_short_and_wrong_passwords(security_gate_store):
    with pytest.raises(ValueError, match="at least"):
        set_gate_password("red-team", new_password="short")

    set_gate_password("red-team", new_password="long-enough-password")
    with pytest.raises(PermissionError, match="invalid password"):
        unlock_gate("red-team", "wrong-password")

    with pytest.raises(PermissionError, match="current password"):
        set_gate_password(
            "red-team",
            new_password="replacement-password",
            current_password="wrong-password",
        )


def test_authorized_catalog_is_ephemeral_and_generic_registry_stays_disabled(security_gate_store):
    set_gate_password("red-team", new_password="red-team-password", enable=True)

    persisted = get_runtime_profile("deephat-7b")
    assert persisted is not None
    assert persisted.enabled is False

    authorized = {profile.name: profile for profile in authorized_runtime_profiles("red-team")}
    assert authorized["deephat-7b"].enabled is True

    # Unlocking the role must not turn generic force_profile into a gate bypass.
    persisted_again = get_runtime_profile("deephat-7b")
    assert persisted_again is not None
    assert persisted_again.enabled is False


def test_security_gate_api_and_role_routing(security_gate_store, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: security_gate_store)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: security_gate_store)
    reset_runtime_profiles()
    client = TestClient(app)

    initial = client.get("/api/runtime-profiles/security-gates")
    assert initial.status_code == 200
    assert all(gate["enabled"] is False for gate in initial.json()["gates"])

    blue_setup = client.put(
        "/api/runtime-profiles/security-gates/blue-team/password",
        json={"new_password": "blue-team-password", "enable": True},
    )
    assert blue_setup.status_code == 200
    assert blue_setup.json()["enabled"] is True

    blue_route = client.post(
        "/api/runtime-profiles/route-role/preview",
        json={"role": "blue-team", "policy": "local-first"},
    )
    assert blue_route.status_code == 200
    assert blue_route.json()["accepted"] is True
    assert blue_route.json()["runtime_profile"]["name"] == "redsage-8b"

    red_setup = client.put(
        "/api/runtime-profiles/security-gates/red-team/password",
        json={"new_password": "red-team-password", "enable": True},
    )
    assert red_setup.status_code == 200

    missing_case = client.post(
        "/api/runtime-profiles/route-role/preview",
        json={"role": "red-team"},
    )
    assert missing_case.status_code == 403
    assert missing_case.json()["detail"]["code"] == "red_authorization_required"

    red_route = client.post(
        "/api/runtime-profiles/route-role/preview",
        json={
            "role": "red-team",
            "authorization_case": "authorized-lab-001",
            "human_confirmed": True,
        },
    )
    assert red_route.status_code == 200
    assert red_route.json()["accepted"] is True
    assert red_route.json()["runtime_profile"]["name"] == "deephat-7b"

    forced_generic = client.post(
        "/api/runtime-profiles/route/preview",
        json={"force_profile": "deephat-7b", "policy": "best-result"},
    )
    assert forced_generic.status_code == 200
    assert forced_generic.json()["accepted"] is False
    assert forced_generic.json()["code"] == "forced_disabled"

    bypass = client.put(
        "/api/runtime-profiles/deephat-7b",
        json={"enabled": True},
    )
    assert bypass.status_code == 403
    assert bypass.json()["detail"]["code"] == "security_gate_managed"
