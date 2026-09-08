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
from .store import database, get, put

BUILD_LOCK = threading.Lock()
JOBS = set()


def job(job_id):
    with database() as db:
        value = get(db, "build", job_id)
    if not value:
        raise HTTPException(404, "Build not found")
    return value


def update(job_id, **changes):
    with database() as db:
        value = get(db, "build", job_id)
        value.update(changes, updated_at=time.time())
        put(db, "build", job_id, value)


def execute(job_id, endpoint):
    try:
        source = repo_root() / "scripts" / "build_android.py"
        spec = importlib.util.spec_from_file_location("jarvis_build_android", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.build(endpoint, progress=lambda text: update(job_id, state="running", activity=text))
        update(job_id, state="completed", result=result, activity="Signed APK ready", finished_at=time.time())
    except Exception as exc:
        update(job_id, state="failed", activity=str(exc)[:300], finished_at=time.time())
    finally:
        BUILD_LOCK.release()


async def start(endpoint):
    if not BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "An Android build is already running")
    job_id = str(uuid.uuid4())
    value = {"id": job_id, "state": "queued", "activity": "Preparing Android build", "started_at": time.time(), "updated_at": time.time()}
    with database() as db:
        put(db, "build", job_id, value)
    task = asyncio.create_task(asyncio.to_thread(execute, job_id, endpoint))
    JOBS.add(task)
    task.add_done_callback(JOBS.discard)
    return value
