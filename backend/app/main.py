from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent.queue_watcher import QUEUE_WATCHER, enqueue_prompt_file
from .api import auth, coding, mcp, memory, mobile, model, queue, runtime_profiles, self_dev, settings, swarm, system, tasks, tools, voice, worker_environments, workflows
from .auth import authenticate_request, authenticate_websocket
from .config import default_allowed_directories, load_settings, logs_dir, repo_root, save_settings
from .db import init_db
from .events import BUS
from .hardware import hardware_dict
from .inference.manager import MANAGER
from .swarm.capabilities import register_localhost_capabilities
from .swarm.nodes import register_localhost_node
from .swarm.workers import bind_workers_to_node
from .tools.mcp_runtime import MCP
from .tools.registry import REGISTRY

logging.basicConfig(level=logging.INFO, filename=str(logs_dir() / "jarvis.log"), filemode="a")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

app = FastAPI(title="Jarvis", version="1.0.0")
settings_obj = load_settings()
origins = [
    f"http://127.0.0.1:{settings_obj.bind_port}",
    f"http://localhost:{settings_obj.bind_port}",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "*",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(queue.router)
app.include_router(system.router)
app.include_router(model.router)
app.include_router(tools.router)
app.include_router(settings.router)
app.include_router(mcp.router)
app.include_router(memory.router)
app.include_router(voice.router)
app.include_router(workflows.router)
app.include_router(self_dev.router)
app.include_router(coding.router)
app.include_router(mobile.router)
app.include_router(swarm.router)
app.include_router(worker_environments.router)
app.include_router(runtime_profiles.router)

frontend_dist = repo_root() / "frontend" / "dist"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not authenticate_request(request):
        return JSONResponse(
            {
                "detail": "Authentication required. Provide a valid private key via Authorization: Bearer, X-Jarvis-Key header, or ?key= query parameter."
            },
            status_code=401,
        )
    return await call_next(request)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    await register_localhost_capabilities(node.id)
    current = load_settings()
    if not current.allowed_directories:
        current.allowed_directories = default_allowed_directories()
        save_settings(current)
    REGISTRY.apply_settings(current)
    logs_dir().mkdir(exist_ok=True)
    Path(repo_root() / "data" / "hardware.json").write_text(json.dumps(hardware_dict(), indent=2), encoding="utf-8")
    if current.mcp_servers:
        try:
            await MCP.refresh(current.mcp_servers)
        except Exception:
            logging.exception("MCP refresh failed")
    if current.inference.auto_load and not os.environ.get("JARVIS_SKIP_MODEL"):
        asyncio.create_task(_autoload_model(current))

    # Check for startup launch prompt passed via environment
    launch_prompt = os.environ.get("JARVIS_LAUNCH_PROMPT")
    if launch_prompt:
        enqueue_prompt_file(launch_prompt)

    launch_prompt_file = os.environ.get("JARVIS_LAUNCH_PROMPT_FILE")
    if launch_prompt_file and Path(launch_prompt_file).exists():
        try:
            content = Path(launch_prompt_file).read_text(encoding="utf-8")
            enqueue_prompt_file(content)
        except Exception:
            logging.exception("Failed to read JARVIS_LAUNCH_PROMPT_FILE %s", launch_prompt_file)

    # Start the background launch queue watcher
    QUEUE_WATCHER.start()
    await QUEUE_WATCHER.process_pending()


@app.on_event("shutdown")
async def shutdown() -> None:
    QUEUE_WATCHER.stop()


async def _autoload_model(current) -> None:
    try:
        await MANAGER.load(current, current.inference.profile)
    except Exception:
        logging.exception("Model auto-load failed; it can be loaded from the Model page")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    if not authenticate_websocket(ws):
        await ws.close(code=4401, reason="Unauthorized: invalid private key")
        return
    await ws.accept()
    queue_bus = BUS.subscribe()
    try:
        while True:
            event = await queue_bus.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        BUS.unsubscribe(queue_bus)


if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = frontend_dist / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
