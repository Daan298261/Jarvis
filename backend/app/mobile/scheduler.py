from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .service import TERMINAL, profile_choice, submit, task_snapshot
from .store import database, get, put, rows

log = logging.getLogger(__name__)


def next_due(schedule: dict, now: float) -> float | None:
    recurrence = schedule["recurrence"]
    if recurrence == "once":
        return None
    zone = ZoneInfo(schedule["timezone"])
    local = datetime.fromtimestamp(schedule["next_run"], zone)
    days = 7 if recurrence == "weekly" else 1
    while local.timestamp() <= now:
        local += timedelta(days=days)
    return local.timestamp()


def validate(values: dict):
    try:
        ZoneInfo(values["timezone"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Unknown timezone")
    profile_choice(values.get("profile"))


def create(device_id: str, values: dict):
    validate(values)
    value = {**values, "id": str(uuid.uuid4()), "device_id": device_id, "enabled": True,
             "last_task_id": None, "last_error": None, "created_at": time.time()}
    with database() as db:
        put(db, "schedule", value["id"], value)
    return value


def update(device_id: str, schedule_id: str, values: dict):
    validate(values)
    with database() as db:
        current = get(db, "schedule", schedule_id)
        if not current or current["device_id"] != device_id:
            raise HTTPException(404, "Schedule not found")
        current.update(values)
        current.update(enabled=True, last_error=None, updated_at=time.time())
        put(db, "schedule", schedule_id, current)
    return current


def resume(device_id: str, schedule_id: str, now: float | None = None):
    now = time.time() if now is None else now
    with database() as db:
        current = get(db, "schedule", schedule_id)
        if not current or current["device_id"] != device_id:
            raise HTTPException(404, "Schedule not found")
        if current["next_run"] <= now:
            following = next_due(current, now)
            if following is None:
                raise HTTPException(409, "Choose a new time before resuming this one-time schedule")
            current["next_run"] = following
        current.update(enabled=True, last_error=None, updated_at=time.time())
        put(db, "schedule", schedule_id, current)
    return current


async def tick(now: float | None = None):
    now = time.time() if now is None else now
    with database() as db:
        schedules = rows(db, "schedule")
    for schedule in schedules:
        if not schedule["enabled"] or schedule["next_run"] > now:
            continue
        with database() as db:
            device = get(db, "device", schedule["device_id"])
        if not device or device["status"] != "active":
            continue
        if schedule.get("last_task_id"):
            try:
                previous = await task_snapshot(schedule["last_task_id"])
                if previous["status"] not in TERMINAL:
                    continue
            except HTTPException:
                pass
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'schedule:{schedule["id"]}:{schedule["next_run"]}'))
        try:
            result = await submit(schedule["device_id"], request_id, schedule["prompt"], schedule.get("profile"))
            following = next_due(schedule, now)
            schedule.update(last_task_id=result["task_id"], last_error=None, last_run=now,
                            enabled=following is not None, next_run=following or schedule["next_run"])
        except Exception as exc:
            schedule["last_error"] = str(getattr(exc, "detail", type(exc).__name__))[:200]
        with database() as db:
            current = get(db, "schedule", schedule["id"])
            if current and current["enabled"]:
                put(db, "schedule", schedule["id"], schedule)


async def run():
    while True:
        try:
            await tick()
        except Exception:
            log.exception("Mobile schedule tick failed")
        await asyncio.sleep(10)
