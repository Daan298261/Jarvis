from app.tools.capabilities import capability_snapshot, optional_workers


def test_browser_use_worker_reflects_install_state():
    workers = {item["id"]: item for item in optional_workers()}
    for key in ("ufo", "cua", "open-interpreter"):
        assert workers[key]["available"] is False
        assert workers[key]["status"] == "not_integrated"
    assert workers["browser-use"]["status"] in {"missing", "ready"}
    assert workers["openhands"]["status"] in {"missing", "ready"}
    if workers["browser-use"]["status"] == "missing":
        assert workers["browser-use"]["available"] is False
    if workers["openhands"]["status"] == "missing":
        assert workers["openhands"]["available"] is False


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
