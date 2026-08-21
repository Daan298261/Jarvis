from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.queue_watcher import QUEUE_WATCHER, enqueue_prompt_file, queue_root

router = APIRouter(prefix="/api/queue", tags=["queue"])


class EnqueueIn(BaseModel):
    prompt: str
    autonomy: str | None = "autonomous"
    profile: str | None = None
    execution_mode: str | None = "balanced"
    filename: str | None = None


def _file_info(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "filename": p.name,
        "size_bytes": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_ctime, timezone.utc).isoformat(),
        "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


@router.get("")
async def get_queue_status():
    root = queue_root()
    pending = [_file_info(f) for f in (root / "pending").iterdir() if f.is_file() and not f.name.startswith(".")]
    # Also top-level root
    for f in root.iterdir():
        if f.is_file() and f.suffix.lower() in {".json", ".prompt", ".txt", ".task"} and not f.name.startswith("."):
            pending.append(_file_info(f))

    processed = sorted(
        [_file_info(f) for f in (root / "processed").iterdir() if f.is_file() and not f.name.startswith(".")],
        key=lambda x: x["modified_at"],
        reverse=True,
    )[:30]

    failed = sorted(
        [_file_info(f) for f in (root / "failed").iterdir() if f.is_file() and not f.name.startswith(".")],
        key=lambda x: x["modified_at"],
        reverse=True,
    )[:30]

    return {
        "queue_directory": str(root),
        "pending_count": len(pending),
        "pending": pending,
        "processed": processed,
        "failed": failed,
    }


@router.post("/enqueue")
async def enqueue_task(body: EnqueueIn):
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    path = enqueue_prompt_file(
        prompt=body.prompt,
        autonomy=body.autonomy,
        profile=body.profile,
        execution_mode=body.execution_mode,
        filename=body.filename,
    )
    # Trigger immediate processing
    task_ids = await QUEUE_WATCHER.process_pending()
    return {
        "ok": True,
        "enqueued_file": str(path),
        "created_task_ids": task_ids,
    }


@router.post("/process")
async def trigger_process():
    task_ids = await QUEUE_WATCHER.process_pending()
    return {"processed_tasks": task_ids, "count": len(task_ids)}
