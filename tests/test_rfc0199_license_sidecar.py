"""RFC-0199 installer license sidecar staging and apply."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.installer import license_sidecar as sidecar
from app.policy.cyber_ato import (
    audit_path,
    issue_license,
    load_installed,
    sealed_license_path,
)


@pytest.fixture
def sidecar_env(tmp_path, monkeypatch):
    app_root = tmp_path / "Jarvis"
    app_root.mkdir()
    data = app_root / "data"
    data.mkdir()
    installer_dir = tmp_path / "usb"
    installer_dir.mkdir()
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: data)
    monkeypatch.setattr("app.licensing.clock_log.data_dir", lambda: data)
    monkeypatch.setattr("app.installer.license_sidecar.data_dir", lambda: data)
    monkeypatch.setattr("app.installer.license_sidecar.repo_root", lambda: app_root)
    return SimpleNamespace(app_root=app_root, data=data, installer_dir=installer_dir)


def _write_sidecar(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_select_sidecar_prefers_jarvis_name(sidecar_env):
    a = sidecar_env.installer_dir / "acme.jarvis-license"
    b = sidecar_env.installer_dir / "Jarvis.jarvis-license"
    a.write_text("{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")
    chosen = sidecar.select_installer_sidecar(sidecar.list_installer_sidecars(sidecar_env.installer_dir))
    assert chosen == b


def test_select_sidecar_lexicographic_when_no_preferred(sidecar_env):
    z = sidecar_env.installer_dir / "zeta.jarvis-license"
    a = sidecar_env.installer_dir / "alpha.jarvis-license"
    z.write_text("{}", encoding="utf-8")
    a.write_text("{}", encoding="utf-8")
    chosen = sidecar.select_installer_sidecar(sidecar.list_installer_sidecars(sidecar_env.installer_dir))
    assert chosen == a


def test_ignore_unrestricted_vendor_sidecar(sidecar_env):
    path = sidecar_env.installer_dir / "Jarvis-unrestricted.jarvis-license"
    path.write_text("{}", encoding="utf-8")
    assert sidecar.list_installer_sidecars(sidecar_env.installer_dir) == []


def test_stage_copies_and_writes_pending(sidecar_env):
    document = issue_license(law_enforcement=True, blue_team=True, red_team=False, valid_days=30, install=False)
    source = sidecar_env.installer_dir / "field.jarvis-license"
    _write_sidecar(source, document)

    result = sidecar.stage_installer_sidecar(
        installer_dir=sidecar_env.installer_dir,
        app_root=sidecar_env.app_root,
    )
    assert result["status"] == "staged"
    residence = sidecar_env.app_root / "license-sidecar" / "field.jarvis-license"
    assert residence.is_file()
    pending = sidecar.read_pending_apply()
    assert pending is not None
    assert pending["source"] == str(residence.resolve())


def test_stage_invalid_sidecar_records_failure_no_pending(sidecar_env):
    bad = sidecar_env.installer_dir / "bad.jarvis-license"
    bad.write_text('{"payload": {}, "signature": "00"}', encoding="utf-8")
    result = sidecar.stage_installer_sidecar(
        installer_dir=sidecar_env.installer_dir,
        app_root=sidecar_env.app_root,
    )
    assert result["status"] == "invalid"
    assert sidecar.read_pending_apply() is None
    failure = json.loads(sidecar.sidecar_failure_path().read_text(encoding="utf-8"))
    assert "invalid" in failure["message"].lower()


def test_stage_skips_when_existing_license_is_newer(sidecar_env):
    existing = issue_license(law_enforcement=True, blue_team=True, red_team=False, valid_days=90, install=True)
    older = dict(existing)
    payload = dict(older["payload"])
    past = datetime.now(timezone.utc) - timedelta(days=1)
    payload["expires_at"] = past.isoformat().replace("+00:00", "Z")
    payload["renew_by"] = payload["expires_at"]
    from app.policy import cyber_ato as mod

    older_doc = mod.sign_license(payload, mod.load_or_create_issuer()[0])
    source = sidecar_env.installer_dir / "older.jarvis-license"
    _write_sidecar(source, older_doc)

    result = sidecar.stage_installer_sidecar(
        installer_dir=sidecar_env.installer_dir,
        app_root=sidecar_env.app_root,
    )
    assert result["status"] == "skipped_upgrade"
    assert sidecar.read_pending_apply() is None
    assert load_installed() is not None


def test_stage_when_sidecar_expires_later(sidecar_env):
    issue_license(law_enforcement=True, blue_team=True, red_team=False, valid_days=10, install=True)
    newer = issue_license(law_enforcement=True, blue_team=True, red_team=False, valid_days=120, install=False)
    source = sidecar_env.installer_dir / "newer.jarvis-license"
    _write_sidecar(source, newer)

    result = sidecar.stage_installer_sidecar(
        installer_dir=sidecar_env.installer_dir,
        app_root=sidecar_env.app_root,
    )
    assert result["status"] == "staged"
    assert sidecar.read_pending_apply() is not None


def test_apply_pending_installs_and_audits(sidecar_env):
    document = issue_license(law_enforcement=True, blue_team=True, red_team=True, valid_days=14, install=False)
    residence = sidecar.sidecar_residence_dir(sidecar_env.app_root) / "apply.jarvis-license"
    _write_sidecar(residence, document)
    sidecar.write_pending_apply(residence_copy=residence, sidecar_source=residence)

    result = sidecar.apply_pending_sidecar_license()
    assert result is not None
    assert result["status"] == "applied"
    assert sidecar.read_pending_apply() is None
    assert sealed_license_path().is_file()
    lines = audit_path().read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines if line.strip()]
    assert "license_auto_applied" in events


def test_apply_pending_failure_honest_banner(sidecar_env):
    bad = sidecar_env.app_root / "license-sidecar" / "forged.jarvis-license"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{"payload": {}, "signature": "00"}', encoding="utf-8")
    sidecar.write_pending_apply(residence_copy=bad, sidecar_source=bad)

    result = sidecar.apply_pending_sidecar_license()
    assert result is not None
    assert result["status"] == "failed"
    assert sidecar.read_pending_apply() is None
    failure = json.loads(sidecar.sidecar_failure_path().read_text(encoding="utf-8"))
    assert failure["message"].startswith("Sidecar license invalid:")


def test_public_sidecar_status_exposes_failure(sidecar_env):
    sidecar.record_sidecar_failure("Sidecar license invalid: test", source="x.jarvis-license")
    status = sidecar.public_sidecar_status()
    assert status["failure"]["message"] == "Sidecar license invalid: test"
