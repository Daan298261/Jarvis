import pytest

from backend.app.integrations.crucix.client import CrucixClient, CrucixError, normalize


def test_normalize_bounds_and_provenance():
    rows=normalize({"meta":{"sourcesOk":1},"news":[{"title":"Example","url":"https://example.test/a","timestamp":"2026-09-24T06:00:00Z"}]})
    assert len(rows)==1
    assert rows[0]["source"]=="news"
    assert rows[0]["verified"] is True
    assert rows[0]["dedup_key"]


def test_rejects_non_loopback_endpoint():
    try:
        CrucixClient("http://192.168.1.10:3117")
    except CrucixError:
        pass
    else:
        raise AssertionError("non-loopback Crucix endpoint accepted")


def test_crucix_install_honors_internet_deny(tmp_path, monkeypatch):
    from app.modules import crucix_runtime
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    def boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("git/npm must not run when internet is denied")

    monkeypatch.setattr(crucix_runtime.subprocess, "run", boom)
    monkeypatch.setattr(crucix_runtime.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(PermissionError):
        crucix_runtime._install_sync()
    assert ran["n"] == 0
