from app.tools.capabilities import capability_snapshot, optional_workers
from app.tools.browser_backends import browser_use_available


def test_browser_use_worker_reflects_install_state():
    workers = {item["id"]: item for item in optional_workers()}
    for key in ("browser-use", "open-interpreter", "openhands"):
        assert workers[key]["available"] is False
        assert workers[key]["status"] == "not_integrated"
    for key in ("ufo", "cua"):
        assert workers[key]["status"] in {"missing", "ready"}
        assert workers[key]["status"] != "not_integrated"


def test_capability_snapshot_includes_native_filesystem():
    snap = capability_snapshot()
    native = {item["id"]: item for item in snap["native"]}
    assert native["filesystem"]["available"] is True
    assert native["git"]["available"] is True
    assert native["office"]["status"] in {"ready", "unavailable"}
    assert len(snap["all"]) == len(snap["native"]) + len(snap["optional_workers"])
    policy = snap["professional_analysis"]
    assert policy["analyze_sensitive_material"] is True
    assert policy["operational_authorization_separate"] is True
