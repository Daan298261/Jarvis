from app.tools.capabilities import capability_snapshot, optional_workers


def test_optional_workers_are_listed_unavailable():
    workers = {item["id"]: item for item in optional_workers()}
    for key in ("browser-use", "ufo", "cua", "openhands"):
        assert workers[key]["available"] is False
        assert workers[key]["status"] == "not_integrated"
    oi = workers["open-interpreter"]
    assert oi["status"] in {"missing", "ready"}
    if not oi["available"]:
        assert oi["status"] == "missing"


def test_capability_snapshot_includes_native_filesystem():
    snap = capability_snapshot()
    native = {item["id"]: item for item in snap["native"]}
    assert native["filesystem"]["available"] is True
    assert len(snap["all"]) == len(snap["native"]) + len(snap["optional_workers"])
