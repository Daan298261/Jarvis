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

from .api import mcp, model, settings, system, tasks, tools, voice
from .config import default_allowed_directories, load_settings, logs_dir, repo_root, save_settings
from .db import init_db
from .events import BUS
from .hardware import hardware_dict
from .inference.manager import MANAGER
from .tools.mcp_runtime import MCP
from .tools.registry import REGISTRY

logging.basicConfig(level=logging.INFO, filename=str(logs_dir() / "jarvis.log"), filemode="a")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

app = FastAPI(title="Jarvis", version="1.0.0")
settings_obj = load_settings()
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
app.include_router(mcp.router)
app.include_router(voice.router)

frontend_dist = repo_root() / "frontend" / "dist"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    current = load_settings()
    if current.lan_access and current.auth_required:
        host = request.client.host if request.client else ""
        local = host in {"127.0.0.1", "::1", "localhost"}
        if not local and request.url.path.startswith("/api"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            header = request.headers.get("x-jarvis-token", "").strip()
            expected = current.auth_token
            if not expected or (token != expected and header != expected):
                return JSONResponse({"detail": "Authentication required for LAN access"}, status_code=401)
    return await call_next(request)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
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
        candidate = frontend_dist / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
