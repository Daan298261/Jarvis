from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.inference.security_gates import (
    authorized_runtime_profiles,
    gate_is_enabled,
    set_gate_password,
    unlock_gate,
)
from app.licensing.entitlements import (
    evaluate_cluster_entitlements,
    has_module,
    module_entitlement_blocked_reason,
)
from app.licensing.modules import module_ids
from app.licensing.vendor_issuer import (
    OWNER_UNRESTRICTED_STABLE_NAME,
    issue_release_unrestricted_license,
    validate_unrestricted_license_payload,
)
from app.persona.hexstrike_overview import HEXSTRIKE_LOAD_OVERVIEW
from app.policy.cyber_ato import issue_license, verify_license


@pytest.fixture
def license_env(jarvis_env, monkeypatch):
    root = jarvis_env["tmp"]
    monkeypatch.setattr("app.inference.security_gates.data_dir", lambda: root)
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: root)
    issuer = root / "issuer"
    issuer.mkdir()
    monkeypatch.setenv("JARVIS_LICENSE_ISSUER_DIR", str(issuer))
    return root


def test_password_unlock_cannot_grant_module_omitted_by_package(license_env):
    issue_license(law_enforcement=True, blue_team=True, red_team=False, valid_days=90, install=True)
    set_gate_password("red-team", new_password="long-red-team-password", enable=True)
    unlock_gate("red-team", "long-red-team-password")
    assert gate_is_enabled("blue-team") is True
    assert gate_is_enabled("red-team") is False


def test_package_alone_enables_when_module_included(license_env):
    issue_license(
        law_enforcement=True,
        blue_team=True,
        red_team=True,
        valid_days=90,
        install=True,
        modules=["blue-team", "red-team", "hexstrike"],
    )
    assert gate_is_enabled("blue-team") is True
    assert gate_is_enabled("red-team") is True
    assert has_module("hexstrike") is True
    profiles = authorized_runtime_profiles("red-team")
    assert any(p.name == "deephat-7b" and p.enabled for p in profiles)


def test_evaluate_cluster_entitlements_merges_package_and_lease(license_env, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.licensing.cluster import ensure_cluster_identity
    from app.licensing.lease import LeasePayload, TEST_SIGNING_PRIVATE_KEY, sign_lease
    from app.licensing.service import refresh_lease
    from app.licensing.store import reset_licensing_store

    root = license_env
    monkeypatch.setattr("app.config.data_dir", lambda: root)
    monkeypatch.setattr("app.licensing.clock_log.data_dir", lambda: root)
    reset_licensing_store()
    cluster_id = ensure_cluster_identity()
    issue_license(
        law_enforcement=False,
        blue_team=True,
        red_team=False,
        valid_days=120,
        install=True,
        modules=["blue-team", "hexstrike"],
    )
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = sign_lease(
        LeasePayload(
            lease_id="lease-rfc0119",
            cluster_id=cluster_id,
            tier="pro",
            features=["swarm"],
            pack_entitlements=["domain.finance"],
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            grace_seconds=3600,
        ),
        TEST_SIGNING_PRIVATE_KEY,
    )
    refresh_lease(lease, now=now)
    entitlements = evaluate_cluster_entitlements(lease)
    assert entitlements["package"]["valid"] is True
    assert "hexstrike" in entitlements["package"]["modules"]
    assert "hexstrike" in entitlements["allowed_modules"]
    assert "blue-team" in entitlements["allowed_modules"]
    assert entitlements["tier"] == "pro"


def test_module_blocked_reason_points_at_package(license_env):
    assert module_entitlement_blocked_reason("hexstrike") is not None
    issue_license(law_enforcement=False, modules=["hexstrike"], valid_days=30, install=True)
    assert module_entitlement_blocked_reason("hexstrike") is None


def test_overview_copy_is_product_level_not_tradecraft():
    text = HEXSTRIKE_LOAD_OVERVIEW.lower()
    assert "embedded operator suite" in text
    assert "loopback" in text
    assert "i will not walk through" in text
    assert not re.search(r"\bstep\s+[0-9]", text)
    assert "curl " not in text
    assert "msfconsole" not in text


def test_issue_release_unrestricted_writes_full_catalog(license_env, tmp_path):
    out = tmp_path / "dist"
    result = issue_release_unrestricted_license(output_dir=out)
    stable = Path(result["stable_path"])
    assert stable.name == OWNER_UNRESTRICTED_STABLE_NAME
    assert stable.is_file()
    sealed = json.loads(stable.read_text(encoding="utf-8"))
    from app.policy.cyber_ato import is_sealed_document, verify_license

    if is_sealed_document(sealed):
        from app.policy.cyber_ato import _open_signed_document

        opened = _open_signed_document(sealed)
    else:
        opened = sealed
    payload = verify_license(opened)
    assert not validate_unrestricted_license_payload(payload)
    assert set(payload["modules"]) == set(module_ids())
    assert payload["law_enforcement"] is True
    assert payload["package_class"] == "owner_unrestricted"


def test_unrestricted_artifact_excluded_from_inno_payload():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "windows" / "Jarvis.iss").read_text(
        encoding="utf-8"
    )
    for line in iss.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source:") and "Jarvis-unrestricted" in stripped and "Excludes:" not in stripped:
            raise AssertionError("Jarvis-unrestricted must not ship inside the customer Inno payload")


def test_build_installer_invokes_unrestricted_issuer():
    script = (Path(__file__).resolve().parents[1] / "installer" / "windows" / "build-installer.ps1").read_text(
        encoding="utf-8"
    )
    assert "issue-release-unrestricted-license.ps1" in script
    assert "Unrestricted license issuance failed" in script
