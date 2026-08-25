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

from .api import backups, mcp, model, phone, settings, system, tasks, tools, voice
from .config import apply_logging_level, default_allowed_directories, load_settings, logs_dir, repo_root, save_settings
from .db import init_db
from .events import BUS
from .hardware import hardware_view
from .inference.manager import MANAGER
from .security import lan_api_denied, usable_auth_token
from .tools.mcp_runtime import MCP
from .tools.registry import REGISTRY

logging.basicConfig(level=logging.INFO, filename=str(logs_dir() / "jarvis.log"), filemode="a")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

app = FastAPI(title="Jarvis", version="1.0.0")
settings_obj = load_settings()
apply_logging_level(settings_obj.logging_level)
origins = [f"http://127.0.0.1:{settings_obj.bind_port}", f"http://localhost:{settings_obj.bind_port}", "http://127.0.0.1:5173", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(system.router)
app.include_router(model.router)
app.include_router(tools.router)
app.include_router(settings.router)
app.include_router(backups.router)
app.include_router(mcp.router)
app.include_router(voice.router)
app.include_router(phone.router)

frontend_dist = repo_root() / "frontend" / "dist"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    current = load_settings()
    host = request.client.host if request.client else ""
    denied = lan_api_denied(
        host,
        request.headers.get("authorization"),
        request.headers.get("x-jarvis-token"),
        current.lan_access,
        usable_auth_token(),
        None,
        allow_query_token=False,
    )
    if denied:
        status, detail = denied
        return JSONResponse({"detail": detail}, status_code=status)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    current = load_settings()
    if not current.allowed_directories:
        current.allowed_directories = default_allowed_directories()
        save_settings(current)
    REGISTRY.apply_settings(current)
    logs_dir().mkdir(exist_ok=True)
    try:
        from .backup import snapshot

        snapshot(reason="startup")
    except Exception:
        logging.exception("Startup backup failed")
    Path(repo_root() / "data" / "hardware.json").write_text(
        json.dumps(hardware_view(), indent=2), encoding="utf-8"
    )
    if current.mcp_servers:
        try:
            await MCP.refresh(current.mcp_servers)
        except Exception:
            logging.exception("MCP refresh failed")
    try:
        from .agent.resume import recover_orphaned_tasks

        restored = await recover_orphaned_tasks()
        if restored:
            logging.info("Marked %s in-flight task(s) interrupted after restart", restored)
    except Exception:
        logging.exception("Failed to recover interrupted tasks")
    if current.inference.auto_load and not os.environ.get("JARVIS_SKIP_MODEL"):
        asyncio.create_task(_autoload_model(current))


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
    current = load_settings()
    host = ws.client.host if ws.client else ""
    denied = lan_api_denied(
        host,
        ws.headers.get("authorization"),
        ws.headers.get("x-jarvis-token"),
        current.lan_access,
        usable_auth_token(),
        ws.query_params.get("token"),
        allow_query_token=True,
    )
    if denied:
        await ws.close(code=1008, reason=denied[1][:120])
        return
    await ws.accept()
    queue = BUS.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        BUS.unsubscribe(queue)


if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        first = (full_path or "").split("/", 1)[0]
        if first in {"phone", "voice", "settings", "system", "history", "model", "tools", "mcp", "tasks"}:
            return FileResponse(frontend_dist / "index.html")
        candidate = frontend_dist / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
