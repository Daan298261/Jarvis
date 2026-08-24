from app.tools.capabilities import capability_snapshot, optional_workers


def test_optional_workers_are_listed_unavailable():
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
    assert len(snap["all"]) == len(snap["native"]) + len(snap["optional_workers"])
