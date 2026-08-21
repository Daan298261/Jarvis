from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .loop import AGENT

logger = logging.getLogger("jarvis.queue")


def queue_root() -> Path:
    path = data_dir() / "queue"
    path.mkdir(parents=True, exist_ok=True)
    (path / "pending").mkdir(parents=True, exist_ok=True)
    (path / "processed").mkdir(parents=True, exist_ok=True)
    (path / "failed").mkdir(parents=True, exist_ok=True)
    return path


def enqueue_prompt_file(
    prompt: str,
    autonomy: str | None = None,
    profile: str | None = None,
    execution_mode: str | None = None,
    filename: str | None = None,
) -> Path:
    root = queue_root()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    name = filename or f"task_{ts}.json"
    if not name.endswith(".json") and not name.endswith(".prompt") and not name.endswith(".txt"):
        name = f"{name}.json"
    target = root / "pending" / name
    payload = {
        "prompt": prompt.strip(),
        "autonomy": autonomy or "autonomous",
        "profile": profile,
        "execution_mode": execution_mode or "balanced",
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def parse_queue_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, dict) or "prompt" not in data:
            raise ValueError("JSON task file must be an object with at least a 'prompt' key")
        return {
            "prompt": str(data["prompt"]).strip(),
            "autonomy": data.get("autonomy") or "autonomous",
            "profile": data.get("profile"),
            "execution_mode": data.get("execution_mode") or "balanced",
        }
    else:
        # Raw text or .prompt file
        return {
            "prompt": text,
            "autonomy": "autonomous",
            "profile": None,
            "execution_mode": "balanced",
        }


class QueueWatcher:
    def __init__(self, poll_interval: float = 2.0) -> None:
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.process_pending()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Error in queue watcher: %s", exc)
            await asyncio.sleep(self.poll_interval)

    async def process_pending(self) -> list[str]:
        root = queue_root()
        pending_dirs = [root / "pending"]
        processed_dir = root / "processed"
        failed_dir = root / "failed"
        processed_tasks = []

        candidates: list[Path] = []
        for pdir in pending_dirs:
            if not pdir.exists():
                continue
            for item in pdir.iterdir():
                if item.is_file() and item.suffix.lower() in {".json", ".prompt", ".txt", ".task"}:
                    if item.name.startswith("."):
                        continue
                    candidates.append(item)

        # Also pick files placed directly in queue root
        for item in root.iterdir():
            if item.is_file() and item.suffix.lower() in {".json", ".prompt", ".txt", ".task"}:
                if not item.name.startswith(".") and item not in candidates:
                    candidates.append(item)

        for filepath in candidates:
            if not filepath.exists():
                continue
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            try:
                task_data = parse_queue_file(filepath)
                prompt = task_data["prompt"]
                if not prompt:
                    raise ValueError("Prompt is empty")

                task = await AGENT.create_task(
                    prompt=prompt,
                    autonomy=task_data.get("autonomy"),
                    profile=task_data.get("profile"),
                    execution_mode=task_data.get("execution_mode"),
                )
                logger.info("Ingested queued task %s from %s", task.id, filepath.name)

                # Move to processed
                dest = processed_dir / f"{ts}_{filepath.name}"
                shutil.move(str(filepath), str(dest))
                processed_tasks.append(task.id)
            except Exception as exc:
                logger.warning("Failed to process queue file %s: %s", filepath.name, exc)
                try:
                    dest = failed_dir / f"{ts}_{filepath.name}"
                    shutil.move(str(filepath), str(dest))
                    err_file = failed_dir / f"{ts}_{filepath.name}.err.txt"
                    err_file.write_text(str(exc), encoding="utf-8")
                except Exception:
                    pass

        return processed_tasks


QUEUE_WATCHER = QueueWatcher()
