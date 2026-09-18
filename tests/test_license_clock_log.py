from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.licensing.clock_log import CLOCK_ROLLBACK_MESSAGE, inspect_clock
from app.policy.cyber_ato import evaluate, issue_license, role_allowed


@pytest.fixture
def ato_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.cyber_ato.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.licensing.clock_log.data_dir", lambda: tmp_path)
    return tmp_path


def test_utc_day_rollback_locks_licensed_modules(ato_store, monkeypatch):
    trusted = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.policy.cyber_ato._utcnow", lambda: trusted)
    issue_license(law_enforcement=True, blue_team=True, red_team=True, install=True)
    inspect_clock(now=trusted, local_offset=120, record=True)
    assert evaluate(now=trusted).valid is True
    assert role_allowed("blue-team", now=trusted) is True

    rolled = trusted - timedelta(days=1)
    verdict = inspect_clock(now=rolled, local_offset=120, record=True)
    assert verdict.locked is True
    assert CLOCK_ROLLBACK_MESSAGE in verdict.reason
    status = evaluate(now=rolled)
    assert status.valid is False
    assert status.clock_rollback is True
    assert role_allowed("blue-team", now=rolled) is False
    assert role_allowed("red-team", now=rolled) is False

    restored = inspect_clock(now=trusted, local_offset=120, record=True)
    assert restored.locked is False
    assert evaluate(now=trusted).valid is True
    assert role_allowed("blue-team", now=trusted) is True


def test_timezone_offset_only_does_not_lock(ato_store, monkeypatch):
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.policy.cyber_ato._utcnow", lambda: now)
    issue_license(law_enforcement=False, blue_team=True, install=True)
    first = inspect_clock(now=now, local_offset=120, record=True)
    assert first.locked is False
    second = inspect_clock(now=now, local_offset=-240, record=True)
    assert second.locked is False
    status = evaluate(now=now)
    assert status.clock_rollback is False
    assert status.valid is True
    assert role_allowed("blue-team", now=now) is True


def test_rfc0012_lease_consults_daily_clock_log(license_store):
    from app.licensing.service import refresh_lease, validate_offline
    from tests.test_license_entitlement import _make_lease

    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    refresh_lease(lease, now=now)
    inspect_clock(now=now, record=True)
    rolled = now - timedelta(days=1)
    result = validate_offline(now=rolled)
    assert result["valid"] is False
    assert result["status"] == "tamper_detected"
    assert "Clock rollback" in result["message"]


@pytest.fixture
def license_store(jarvis_env, monkeypatch):
    from app.licensing.cluster import ensure_cluster_identity
    from app.licensing.store import reset_licensing_store

    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.licensing.clock_log.data_dir", lambda: jarvis_env["tmp"])
    reset_licensing_store()
    cluster_id = ensure_cluster_identity()
    return {"tmp": jarvis_env["tmp"], "cluster_id": cluster_id}
