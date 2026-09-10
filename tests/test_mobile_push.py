import pytest

from app.mobile import runtime, store


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def device():
    return {"id": "phone", "status": "active", "push_token": "registration",
            "notifications": True, "critical_calls": True}


@pytest.mark.asyncio
async def test_failed_push_is_persisted_and_retried(mobile_env, monkeypatch):
    with store.database() as db:
        store.put(db, "device", "phone", device())
    attempts = []
    async def send(target, event_id, kind):
        attempts.append((event_id, kind))
        return len(attempts) > 1
    monkeypatch.setattr(runtime, "push", send)
    queued = runtime.enqueue_push(device(), "task-one", "task", now=1000)
    assert not await runtime.deliver_one(queued, now=1000)
    with store.database() as db:
        pending = store.get(db, "push", queued["id"])
    assert pending["attempts"] == 1 and pending["next_attempt_at"] == 1005
    assert not await runtime.deliver_one(queued, now=1004)
    assert await runtime.deliver_one(queued, now=1005)
    with store.database() as db:
        assert store.get(db, "push", queued["id"]) is None
        assert store.get(db, "notification", queued["key"])
    assert attempts == [("task-one", "task"), ("task-one", "task")]


@pytest.mark.asyncio
async def test_push_dedup_and_preference_revocation(mobile_env, monkeypatch):
    muted = {**device(), "notifications": False}
    with store.database() as db:
        store.put(db, "device", "phone", muted)
    sent = []
    async def send(*args):
        sent.append(args)
        return True
    monkeypatch.setattr(runtime, "push", send)
    queued = runtime.enqueue_push(muted, "task-two", "task", now=2000)
    assert not await runtime.deliver_one(queued, now=2000)
    with store.database() as db:
        assert store.get(db, "push", queued["id"]) is None
    active = device()
    with store.database() as db:
        store.put(db, "device", "phone", active)
    first = runtime.enqueue_push(active, "call-one", "call", expires_at=3000, now=2500)
    assert await runtime.deliver_one(first, now=2500)
    duplicate = runtime.enqueue_push(active, "call-one", "call", expires_at=3000, now=2501)
    assert duplicate["already_sent"] and await runtime.deliver_one(duplicate, now=2501)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_expired_call_wake_is_removed_without_sending(mobile_env, monkeypatch):
    with store.database() as db:
        store.put(db, "device", "phone", device())
    async def forbidden(*args):
        pytest.fail("expired push must not be sent")
    monkeypatch.setattr(runtime, "push", forbidden)
    queued = runtime.enqueue_push(device(), "expired-call", "call", expires_at=10, now=9)
    assert not await runtime.deliver_one(queued, now=11)


def test_waiting_and_completed_task_updates_have_distinct_dedup_keys(mobile_env):
    waiting = runtime.enqueue_push(device(), "task-three", "task", now=1, dedupe="waiting")
    completed = runtime.enqueue_push(device(), "task-three", "task", now=1, dedupe="completed")
    assert waiting["id"] != completed["id"]
