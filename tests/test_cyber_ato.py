from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy.cyber_ato import (
    AtoError,
    evaluate,
    issue_license,
    main,
    renew_license,
    revoke_license,
    role_allowed,
    verify_license,
)


@pytest.fixture
def ato_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.licensing.clock_log.data_dir", lambda: tmp_path)
    return tmp_path


def test_issue_requires_le_for_red(ato_store):
    with pytest.raises(AtoError, match="law-enforcement"):
        issue_license(law_enforcement=False, blue_team=False, red_team=True, install=True)


def test_blue_without_le_is_allowed(ato_store):
    document = issue_license(law_enforcement=False, blue_team=True, red_team=False, install=True)
    payload = verify_license(document)
    assert payload["in_person_verified"] is True
    assert payload["law_enforcement"] is False
    status = evaluate()
    assert status.valid is True
    assert role_allowed("blue-team") is True
    assert role_allowed("red-team") is False


def test_red_with_le_unlocks_red_runtime(ato_store):
    issue_license(law_enforcement=True, blue_team=True, red_team=True, valid_days=30, renew_in_days=20, install=True)
    status = evaluate()
    assert status.law_enforcement is True
    assert status.red_team is True
    assert role_allowed("red-team") is True
    assert "renew" in status.renew_by.lower() or status.renew_by


def test_expired_license_is_not_valid(ato_store, monkeypatch):
    document = issue_license(law_enforcement=True, blue_team=True, red_team=True, valid_days=1, install=True)
    payload = document["payload"]
    past = datetime.now(timezone.utc) - timedelta(days=2)
    payload["issued_at"] = past.isoformat().replace("+00:00", "Z")
    payload["not_before"] = payload["issued_at"]
    payload["expires_at"] = (past + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload["renew_by"] = payload["expires_at"]
    from app.policy import cyber_ato as mod

    private, _public = mod.load_or_create_issuer()
    expired = mod.sign_license(payload, private)
    mod.install_license(expired)
    status = evaluate()
    assert status.valid is False
    assert status.expired is True
    assert role_allowed("blue-team") is False
    assert role_allowed("red-team") is False


def test_cli_issue_prints_json(ato_store, capsys):
    assert main(["issue", "--le", "--red", "--days", "14", "--renew-in", "10", "--install"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["payload"]["law_enforcement"] is True
    assert printed["payload"]["red_team"] is True
    assert evaluate().valid is True


def test_renew_and_api(ato_store):
    issue_license(law_enforcement=True, blue_team=True, red_team=True, valid_days=10, install=True)
    first = evaluate().license_id
    renewed = renew_license(valid_days=40, renew_in_days=30, install=True)
    assert renewed["payload"]["license_id"] != first
    assert evaluate().valid is True

    client = TestClient(app)
    status = client.get("/api/cyber-ato/status")
    assert status.status_code == 200
    assert status.json()["valid"] is True
    assert status.json()["law_enforcement"] is True

    revoked = client.post("/api/cyber-ato/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["installed"] is False

    issued = client.post(
        "/api/cyber-ato/issue",
        json={
            "law_enforcement": True,
            "blue_team": True,
            "red_team": True,
            "valid_days": 21,
            "renew_in_days": 14,
            "case_ref": "in-person-1",
            "install": True,
        },
    )
    assert issued.status_code == 200
    assert issued.json()["status"]["case_ref"] == "in-person-1"
    assert issued.json()["license"]["payload"]["in_person_verified"] is True

    refuse_red = client.post(
        "/api/cyber-ato/issue",
        json={"law_enforcement": False, "blue_team": False, "red_team": True, "install": False},
    )
    assert refuse_red.status_code == 400


def test_revoke_clears_runtime(ato_store):
    issue_license(law_enforcement=True, blue_team=True, red_team=True, install=True)
    revoke_license()
    assert evaluate().installed is False
    assert role_allowed("blue-team") is False


def test_sealed_license_roundtrip(ato_store):
    from app.policy.cyber_ato import install_license, load_installed, sealed_license_path
    from app.licensing.seal import is_sealed_document

    document = issue_license(
        law_enforcement=True,
        blue_team=True,
        red_team=True,
        valid_days=30,
        install=True,
        licensee_name="Ada",
        licensee_email="ada@example.com",
        modules=["blue-team", "red-team", "hexstrike"],
    )
    stored = load_installed()
    assert stored is not None
    assert is_sealed_document(stored)
    assert sealed_license_path().is_file()
    payload = verify_license(stored)
    assert payload["licensee_email"] == "ada@example.com"
    assert "hexstrike" in payload["modules"]
    assert evaluate().valid is True
    assert role_allowed("hexstrike") is True

    forged = dict(document)
    forged["signature"] = "00" * 64
    with pytest.raises(AtoError, match="not valid"):
        install_license(forged)


def test_unsigned_license_fails(ato_store):
    from app.policy.cyber_ato import KIND, install_license

    with pytest.raises(AtoError):
        install_license(
            {
                "payload": {
                    "v": 1,
                    "kind": KIND,
                    "license_id": "x",
                    "in_person_verified": True,
                    "law_enforcement": True,
                    "blue_team": True,
                    "red_team": True,
                    "issued_at": "2026-09-14T00:00:00Z",
                    "not_before": "2026-09-14T00:00:00Z",
                    "expires_at": "2027-09-14T00:00:00Z",
                    "renew_by": "2027-09-14T00:00:00Z",
                },
                "signature": "",
                "public_key": "",
            }
        )


def test_autorenew_capped_by_max_expires_at(ato_store, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.policy import cyber_ato as mod

    document = issue_license(
        law_enforcement=False,
        blue_team=True,
        valid_days=10,
        auto_renew=True,
        term_days=10,
        max_days=25,
        install=True,
    )
    payload = document["payload"]
    issued = datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00"))
    after_first_term = issued + timedelta(days=15)
    monkeypatch.setattr(mod, "_utcnow", lambda: after_first_term.replace(microsecond=0))
    status = evaluate(now=after_first_term)
    assert status.valid is True
    assert status.auto_renew is True

    past_cap = issued + timedelta(days=40)
    monkeypatch.setattr(mod, "_utcnow", lambda: past_cap.replace(microsecond=0))
    status = evaluate(now=past_cap)
    assert status.valid is False
    assert status.expired is True


def test_vendor_issuer_requires_le_for_red(ato_store, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LICENSE_ISSUER_DIR", str(tmp_path / "issuer"))
    from app.licensing.vendor_issuer import issue_customer_license

    with pytest.raises(AtoError, match="law-enforcement"):
        issue_customer_license(
            name="Ada",
            email="ada@example.com",
            law_enforcement=False,
            modules=["red-team"],
            output_dir=tmp_path / "out",
        )


def test_vendor_sealed_file_verifies(ato_store, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LICENSE_ISSUER_DIR", str(tmp_path / "issuer"))
    from app.licensing.vendor_issuer import issue_customer_license, vendor_public_hex
    from app.policy.cyber_ato import install_license, revoke_license

    result = issue_customer_license(
        name="Ada Lovelace",
        email="ada@example.com",
        address="London",
        law_enforcement=True,
        modules=["blue-team", "red-team", "computer-use"],
        term_days=30,
        max_days=90,
        auto_renew=True,
        output_dir=tmp_path / "out",
    )
    sealed = json.loads(Path(result["sealed_path"]).read_text(encoding="utf-8"))
    monkeypatch.setenv("JARVIS_ATO_PUBLIC_KEY", vendor_public_hex())
    revoke_license()
    install_license(sealed)
    status = evaluate()
    assert status.valid is True
    assert status.law_enforcement is True
    assert "computer-use" in status.modules
    assert role_allowed("red-team") is True

