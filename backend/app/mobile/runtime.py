from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import httpx

from . import calls, scheduler
from .store import database, get, put, rows
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


class MobileRuntime:
    def __init__(self):
        self.tasks = []

    def start(self):
        if not self.tasks:
            self.tasks = [asyncio.create_task(scheduler.run()), asyncio.create_task(self.notifications()), asyncio.create_task(self.reap_calls())]

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
                    key = f'{device["id"]}:{event["task_id"]}:{event["kind"]}'
                    with database() as db:
                        if get(db, "notification", key):
                            continue
                    try:
                        if await push(device, event["task_id"], "task"):
                            with database() as db:
                                put(db, "notification", key, {"sent_at": time.time()})
                    except Exception:
                        log.warning("Mobile push delivery failed; task remains available in history")
        finally:
            BUS.unsubscribe(queue)

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
