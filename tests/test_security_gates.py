from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.inference.runtime_profiles import get_runtime_profile, reset_runtime_profiles
from app.inference.security_gates import authorized_runtime_profiles, gate_is_enabled
from app.main import app
from app.policy.cyber_ato import issue_license


@pytest.fixture
def security_gate_store(jarvis_env, monkeypatch):
    root = jarvis_env["tmp"]
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: root)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: root)
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: root)
    reset_runtime_profiles()
    issue_license(
        law_enforcement=True,
        blue_team=True,
        red_team=True,
        valid_days=90,
        install=True,
        modules=["blue-team", "red-team"],
    )
    return root


def test_gate_is_enabled_follows_license_package(security_gate_store):
    assert gate_is_enabled("blue-team") is True
    assert gate_is_enabled("red-team") is True


def test_authorized_catalog_is_ephemeral_and_generic_registry_stays_disabled(security_gate_store):
    persisted = get_runtime_profile("deephat-7b")
    assert persisted is not None
    assert persisted.enabled is False

    authorized = {profile.name: profile for profile in authorized_runtime_profiles("red-team")}
    assert authorized["deephat-7b"].enabled is True

    persisted_again = get_runtime_profile("deephat-7b")
    assert persisted_again is not None
    assert persisted_again.enabled is False


def test_security_gate_api_and_role_routing(security_gate_store, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: security_gate_store)
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: security_gate_store)
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: security_gate_store)
    reset_runtime_profiles()
    client = TestClient(app)

    initial = client.get("/api/runtime-profiles/security-gates")
    assert initial.status_code == 200
    blue_gate = next(g for g in initial.json()["gates"] if g["role"] == "blue-team")
    assert blue_gate["ops_allowed"] is True

    blue_route = client.post(
        "/api/runtime-profiles/route-role/preview",
        json={"role": "blue-team", "policy": "local-first"},
    )
    assert blue_route.status_code == 200
    assert blue_route.json()["accepted"] is True
    assert blue_route.json()["runtime_profile"]["name"] == "redsage-8b"

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

    retired = client.post(
        "/api/runtime-profiles/security-gates/blue-team/unlock",
        json={"password": "any-password-here"},
    )
    assert retired.status_code == 410
