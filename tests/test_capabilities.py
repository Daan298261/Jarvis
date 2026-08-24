from app.tools.capabilities import capability_snapshot, optional_workers


def test_optional_workers_are_listed_unavailable():
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
    assert len(snap["all"]) == len(snap["native"]) + len(snap["optional_workers"])
