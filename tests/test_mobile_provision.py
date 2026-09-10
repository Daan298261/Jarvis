import time

import pytest

from app.mobile import provision, store


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def test_interrupted_builds_are_failed_on_restart(mobile_env):
    with store.database() as db:
        store.put(db, "build", "running", {"id": "running", "state": "running", "activity": "Compiling",
                                             "started_at": 1, "updated_at": 2})
        store.put(db, "build", "done", {"id": "done", "state": "completed", "activity": "Ready",
                                          "started_at": 1, "updated_at": 2})
    assert provision.recover_interrupted() == 1
    assert provision.job("running")["state"] == "failed"
    assert provision.job("done")["state"] == "completed"


def test_build_status_marks_missing_heartbeat_stale(mobile_env, monkeypatch):
    monkeypatch.setattr(provision.time, "time", lambda: 100)
    with store.database() as db:
        store.put(db, "build", "old", {"id": "old", "state": "running", "activity": "Compiling",
                                         "started_at": 1, "updated_at": 60})
        store.put(db, "build", "live", {"id": "live", "state": "running", "activity": "Compiling",
                                          "started_at": 1, "updated_at": 80})
    assert provision.job("old")["stale"]
    assert not provision.job("live")["stale"]
