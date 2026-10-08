"""Exercise the real ANZU task loop against an existing local model endpoint."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


async def verify(args):
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["JARVIS_ROOT"] = str(workspace)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.config import AppSettings, save_settings
    from app.db.session import init_db, SessionLocal, dispose_database_engine
    from app.db.models import Task
    from app.inference.manager import MANAGER
    from app.providers.openai_compat import OpenAICompatProvider
    from app.tools.registry import REGISTRY
    from app.agent.loop import AGENT
    from app.reverse_engineering import store
    from app.reverse_engineering.runtime import SERVICE

    target = workspace / "fixture.py"
    target.write_text("def storage_key():\n    return 'ANZU_CHAT_STORAGE_V1'\n", encoding="utf-8")
    settings = AppSettings(allowed_directories=[str(workspace)], autonomy="autonomous", backup_enabled=False)
    settings.front_responder.enabled = False
    settings.inference.auto_load = False
    settings.inference.remote_model = args.model
    save_settings(settings)
    await init_db()
    MANAGER.provider = OpenAICompatProvider(base_url=args.endpoint, model=args.model)
    MANAGER.state.loaded = True
    MANAGER.state.profile = "balanced"
    MANAGER.state.context_size = 32768
    MANAGER.state.server_n_ctx = 32768
    MANAGER.state.manages_process = False
    REGISTRY.apply_settings(settings)
    try:
        task = await AGENT.create_task(f"Reverse engineer {target}. What exact storage key does storage_key return? Cite saved evidence and produce an investigation report.", profile="balanced")
        await asyncio.wait_for(asyncio.shield(AGENT._tasks[task.id]), args.timeout)
        async with SessionLocal() as session:
            row = await session.get(Task, task.id)
            result = {"task_id": task.id, "status": row.status, "result": row.result, "error": row.error}
        reports = store.list_rows(task.id)
        result["investigations"] = [{"id": r["id"], "status": r["status"], "findings": r["findings"], "unknowns": r["unknowns"]} for r in reports]
        store.atomic_json(workspace / "chat-acceptance.json", result)
        print(json.dumps(result, indent=2))
        assert result["status"] == "completed", result
        assert any("ANZU_CHAT_STORAGE_V1" in json.dumps(r["findings"]) for r in reports), "Chat did not recover and report the known fixture value"
    finally:
        for task in list(AGENT._tasks.values()) + list(AGENT._heartbeat_tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*AGENT._tasks.values(), *AGENT._heartbeat_tasks.values(), return_exceptions=True)
        await SERVICE.shutdown()
        await MANAGER.provider.client.close()
        await dispose_database_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", default=str(Path.home() / ".anzu/acceptance/rfc0200/chat"))
    parser.add_argument("--timeout", type=int, default=900)
    asyncio.run(verify(parser.parse_args()))
