import json
import pytest

from app.agent.queue_watcher import QUEUE_WATCHER, enqueue_prompt_file, parse_queue_file, queue_root
from app.db.models import Task
from app.db.session import SessionLocal


def test_enqueue_and_parse_prompt_file(jarvis_env):
    path = enqueue_prompt_file(
        prompt="Organize my desktop into folders",
        autonomy="autonomous",
        execution_mode="reliable",
        filename="custom_task.json",
    )
    assert path.exists()
    parsed = parse_queue_file(path)
    assert parsed["prompt"] == "Organize my desktop into folders"
    assert parsed["autonomy"] == "autonomous"
    assert parsed["execution_mode"] == "reliable"


async def test_queue_watcher_processes_pending_and_moves_to_processed(jarvis_env):
    from app.agent.loop import AGENT
    from app.providers.base import ChatResult

    class FakeProvider:
        async def health(self): return True
        async def chat(self, *args, **kwargs): return ChatResult(content="Done")

    jarvis_env["manager"].provider = FakeProvider()

    enqueue_prompt_file(
        prompt="Check system status and report back",
        autonomy="autonomous",
        execution_mode="fast",
        filename="boot_task.json",
    )

    task_ids = await QUEUE_WATCHER.process_pending()
    assert len(task_ids) == 1
    task_id = task_ids[0]

    # Wait for the task runner to complete cleanly
    if task_id in AGENT._tasks:
        await AGENT._tasks[task_id]

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.prompt == "Check system status and report back"
        assert task.execution_mode == "fast"

    root = queue_root()
    # Check that pending is now empty
    pending_files = [f for f in (root / "pending").iterdir() if f.is_file() and not f.name.startswith(".")]
    assert len(pending_files) == 0

    # Check that processed folder has the file
    processed_files = [f for f in (root / "processed").iterdir() if f.is_file() and not f.name.startswith(".")]
    assert len(processed_files) >= 1
