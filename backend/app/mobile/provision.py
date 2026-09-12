"""Desktop-controlled provisioning jobs, with concrete progress and local artifacts."""
from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from ..config import repo_root
from .store import database, get, put, rows

BUILD_LOCK = threading.Lock()
JOBS = set()


def job(job_id):
    with database() as db:
        value = get(db, "build", job_id)
    if not value:
        raise HTTPException(404, "Build not found")
    value["stale"] = value["state"] in {"queued", "running"} and time.time() - value["updated_at"] > 30
    return value


def update(job_id, **changes):
    with database() as db:
        value = get(db, "build", job_id)
        value.update(changes, updated_at=time.time())
        put(db, "build", job_id, value)


def execute(job_id, endpoint, endpoints, *, generic: bool = False):
    stopped = threading.Event()
    activity = ["Preparing Android build"]

    def heartbeat():
        while not stopped.wait(10):
            update(job_id, state="running", activity=activity[0], heartbeat_at=time.time())

    def progress(text):
        activity[0] = text
        update(job_id, state="running", activity=text, heartbeat_at=time.time())

    monitor = threading.Thread(target=heartbeat, name=f"android-build-heartbeat-{job_id[:8]}", daemon=True)
    monitor.start()
    try:
        source = repo_root() / "scripts" / "build_android.py"
        spec = importlib.util.spec_from_file_location("jarvis_build_android", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if generic:
            result = module.build(progress=progress, generic=True)
        else:
            result = module.build(endpoint, endpoints=endpoints, progress=progress, generic=False)
        update(
            job_id,
            state="completed",
            result=result,
            activity="Signed APK ready",
            mode=result.get("mode") or ("generic" if generic else "personalized"),
            finished_at=time.time(),
        )
    except Exception as exc:
        update(job_id, state="failed", activity=str(exc)[:300], finished_at=time.time())
    finally:
        stopped.set()
        monitor.join(timeout=2)
        BUILD_LOCK.release()


def recover_interrupted():
    recovered = 0
    with database() as db:
        builds = rows(db, "build")
        for value in builds:
            if value["state"] in {"queued", "running"}:
                value.update(state="failed", activity="Jarvis restarted before this build finished; start a new build",
                             finished_at=time.time(), updated_at=time.time(), stale=False)
                put(db, "build", value["id"], value)
                recovered += 1
    return recovered


async def start(endpoint, endpoints=None, *, generic: bool = False):
    if not BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "An Android build is already running")
    job_id = str(uuid.uuid4())
    mode = "generic" if generic else "personalized"
    value = {
        "id": job_id,
        "state": "queued",
        "activity": "Preparing generic companion APK" if generic else "Preparing Android build",
        "worker": "Android builder",
        "mode": mode,
        "started_at": time.time(),
        "updated_at": time.time(),
        "heartbeat_at": time.time(),
        "stale": False,
    }
    with database() as db:
        put(db, "build", job_id, value)
    task = asyncio.create_task(
        asyncio.to_thread(execute, job_id, endpoint or "", endpoints or [], generic=generic)
    )
    JOBS.add(task)
    task.add_done_callback(JOBS.discard)
    return value
