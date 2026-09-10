from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time

import httpx

from . import calls, scheduler
from .store import database, delete, get, put, rows
from ..events import BUS

log = logging.getLogger(__name__)


async def push(device: dict, event_id: str, kind: str):
    url = os.environ.get("JARVIS_PUSH_URL", "")
    token = os.environ.get("JARVIS_PUSH_CREDENTIAL", "")
    if not url or not token or not device.get("push_token"):
        return False
    if not url.startswith("https://"):
        raise ValueError("Push endpoint must use HTTPS")
    # No conversation text, attachments or provider credentials in push payloads.
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {token}"},
                                     json={"token": device["push_token"], "data": {"event_id": event_id, "kind": kind}})
        response.raise_for_status()
    return True


def enqueue_push(device: dict, event_id: str, kind: str, expires_at: float | None = None,
                 now: float | None = None, dedupe: str = ""):
    now = time.time() if now is None else now
    key = f'{device["id"]}:{event_id}:{kind}:{dedupe}'
    record_id = hashlib.sha256(key.encode()).hexdigest()
    with database() as db:
        if get(db, "notification", key):
            return {"id": record_id, "key": key, "already_sent": True}
        current = get(db, "push", record_id)
        if current:
            return current
        current = {"id": record_id, "key": key, "device_id": device["id"], "event_id": event_id,
                   "kind": kind, "attempts": 0, "next_attempt_at": now,
                   "expires_at": expires_at or now + 86400, "created_at": now}
        put(db, "push", record_id, current)
    return current


async def deliver_one(record: dict, now: float | None = None):
    if record.get("already_sent"):
        return True
    now = time.time() if now is None else now
    with database() as db:
        current = get(db, "push", record["id"])
        device = get(db, "device", record["device_id"])
    if not current:
        return True
    allowed = bool(device and device["status"] == "active" and device.get("push_token"))
    allowed = allowed and bool(device.get("critical_calls") if current["kind"] == "call" else device.get("notifications"))
    if current["expires_at"] <= now or not allowed:
        with database() as db:
            delete(db, "push", current["id"])
        return False
    if current["next_attempt_at"] > now:
        return False
    try:
        delivered = await push(device, current["event_id"], current["kind"])
    except Exception:
        delivered = False
    with database() as db:
        latest = get(db, "push", current["id"])
        if not latest:
            return delivered
        if delivered:
            delete(db, "push", current["id"])
            put(db, "notification", current["key"], {"sent_at": now})
        else:
            attempts = int(latest.get("attempts", 0)) + 1
            latest.update(attempts=attempts, last_attempt_at=now,
                          next_attempt_at=now + min(300, 5 * (2 ** min(attempts - 1, 6))))
            put(db, "push", current["id"], latest)
    return delivered


async def deliver_pending_once(now: float | None = None):
    with database() as db:
        pending = sorted(rows(db, "push"), key=lambda item: item["created_at"])[:100]
    for record in pending:
        await deliver_one(record, now)


class MobileRuntime:
    def __init__(self):
        self.tasks = []

    def start(self):
        if not self.tasks:
            from .connectivity import CONNECTIVITY
            self.tasks = [asyncio.create_task(scheduler.run()), asyncio.create_task(self.notifications()),
                          asyncio.create_task(self.reap_calls()), asyncio.create_task(self.deliver_pushes())]
            self.tasks.append(asyncio.create_task(CONNECTIVITY.run()))
            if os.environ.get("JARVIS_RELAY_URL") and os.environ.get("JARVIS_RELAY_CREDENTIAL"):
                from .relay import run
                self.tasks.append(asyncio.create_task(run(os.environ["JARVIS_RELAY_URL"], os.environ["JARVIS_RELAY_CREDENTIAL"])))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        for peer in list(calls.PEERS.values()):
            await peer.close()
        calls.PEERS.clear()

    async def notifications(self):
        queue = BUS.subscribe()
        try:
            while True:
                event = await queue.get()
                if event["kind"] not in {"completed", "failed", "waiting", "task_completed", "task_failed", "confirmation"}:
                    continue
                with database() as db:
                    devices = rows(db, "device")
                for device in devices:
                    if device["status"] != "active" or not device.get("notifications"):
                        continue
                    enqueue_push(device, event["task_id"], "task", dedupe=event["kind"])
        finally:
            BUS.unsubscribe(queue)

    async def deliver_pushes(self):
        while True:
            try:
                await deliver_pending_once()
            except Exception:
                log.exception("Mobile push retry loop failed")
            await asyncio.sleep(5)

    async def reap_calls(self):
        while True:
            with database() as db:
                items = rows(db, "call")
            for call in items:
                with database() as db:
                    device = get(db, "device", call["device_id"])
                expired = call["expires_at"] < time.time()
                revoked = not device or device["status"] != "active"
                if call["state"] in calls.ACTIVE_STATES and (expired or revoked):
                    peer = calls.PEERS.pop(call["id"], None)
                    if peer:
                        await peer.close()
                    calls.update(call["id"], state="missed" if call["state"] == "ringing" else "ended")
            await asyncio.sleep(5)
