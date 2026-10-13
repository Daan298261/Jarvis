"""Paired-device tool queue; the phone remains the authority for every action."""
from __future__ import annotations
import time
import uuid
from fastapi import HTTPException
from .store import database, get, put, rows, delete

ACTIONS = {"launch", "read", "tap", "scroll", "back", "text"}


def enqueue(device_id: str, command: dict) -> dict:
    if command.get("action") not in ACTIONS or not command.get("package"):
        raise HTTPException(400, "Choose a supported phone action and target package")
    with database() as db:
        for record in rows(db, "phone_tool"):
            if record["expires_at"] < time.time() - 3600:
                delete(db, "phone_tool", record["id"])
        device = get(db, "device", device_id)
        if not device or device.get("status") != "active":
            raise HTTPException(403, "Phone must be paired and active")
        pending = [r for r in rows(db, "phone_tool") if r["device_id"] == device_id and r["status"] == "pending" and r["expires_at"] > time.time()]
        if len(pending) >= 10:
            raise HTTPException(409, "Phone action queue is full")
        item = {"id": str(uuid.uuid4()), "device_id": device_id, "command": command,
                "status": "pending", "expires_at": time.time() + 120}
        put(db, "phone_tool", item["id"], item)
    return item


def pending(device_id: str) -> list[dict]:
    with database() as db:
        return [r for r in rows(db, "phone_tool") if r["device_id"] == device_id and r["status"] == "pending" and r["expires_at"] > time.time()]


def finish(device_id: str, item_id: str, result: dict) -> dict:
    with database() as db:
        item = get(db, "phone_tool", item_id)
        if not item or item["device_id"] != device_id:
            raise HTTPException(404, "Phone action not found")
        if item["status"] != "pending" or item["expires_at"] <= time.time():
            raise HTTPException(409, "Phone action expired or already finished")
        item.update(status="finished", result=result)
        put(db, "phone_tool", item_id, item)
    return item
