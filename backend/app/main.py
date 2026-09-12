from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__

from .agent.queue_watcher import QUEUE_WATCHER, enqueue_prompt_file
from .api import advisor, agent_policy, agent_portability, amazon_ads, auth, autonomy, coding, companion, computer_use, context_repo, delegation, diagnostics, guest_portals, help as help_api, hexstrike, ingest, integrations, license, lmstudio, mcp, memory, mobile, model, owner_chat, packs, perception, perception_identity, permissions, queue, runtime_profiles, self_dev, settings, setup, swarm, system, tasks, tools, trajectories, voice, voice_profiles, worker_environments, workflows
from .auth import authenticate_request, authenticate_websocket
from .guests.service import authenticate_guest_request, extract_guest_token_from_request
from .config import default_allowed_directories, load_settings, logs_dir, repo_root, save_settings
from .db import init_db
from .events import BUS
from .hardware import hardware_dict
from .inference.manager import MANAGER
from .inference.profiles import preferred_startup_profile
from .integrations.setup import WHATSAPP_PAIRING
from .swarm.capabilities import register_localhost_capabilities
from .swarm.nodes import register_localhost_node
from .swarm.workers import bind_workers_to_node
from .tools.mcp_runtime import MCP
from .tools.registry import REGISTRY
from .mobile.calls import router as companion_calls_router
from .mobile.runtime import MobileRuntime

logging.basicConfig(level=logging.INFO, filename=str(logs_dir() / "jarvis.log"), filemode="a")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

app = FastAPI(title="Jarvis", version=__version__)
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
app.include_router(delegation.router)
app.include_router(advisor.router)
app.include_router(queue.router)
app.include_router(system.router)
app.include_router(model.router)
app.include_router(tools.router)
app.include_router(settings.router)
app.include_router(mcp.router)
app.include_router(memory.router)
app.include_router(voice.router)
app.include_router(owner_chat.router)
app.include_router(help_api.router)
app.include_router(voice_profiles.router)
app.include_router(workflows.router)
app.include_router(self_dev.router)
app.include_router(coding.router)
app.include_router(mobile.router)
app.include_router(companion.router)
app.include_router(companion.owner_router)
app.include_router(swarm.router)
app.include_router(worker_environments.router)
app.include_router(runtime_profiles.router)
app.include_router(hexstrike.router)
app.include_router(permissions.router)
app.include_router(computer_use.router)
app.include_router(lmstudio.router)
app.include_router(packs.router)
app.include_router(trajectories.router)
app.include_router(context_repo.router)
app.include_router(agent_portability.router)
app.include_router(guest_portals.owner_router)
app.include_router(guest_portals.guest_router)
app.include_router(license.router)
app.include_router(autonomy.router)
app.include_router(agent_policy.router)
app.include_router(amazon_ads.router)
app.include_router(setup.router)
app.include_router(integrations.router)
app.include_router(diagnostics.router)
app.include_router(ingest.router)
app.include_router(perception.router)
app.include_router(perception_identity.router)
app.include_router(companion_calls_router)
mobile_runtime = MobileRuntime()

frontend_dist = repo_root() / "frontend" / "dist"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Companion routes enforce device proof/session auth even on localhost.
    # They never inherit the owner's key or the desktop convenience exemption.
    if request.url.path.startswith("/api/companion/"):
        return await call_next(request)
    if authenticate_request(request):
        return await call_next(request)

    path = request.url.path
    if path.startswith("/api/guest/"):
        guest_ctx = authenticate_guest_request(request)
        if guest_ctx is not None:
            request.state.guest = guest_ctx
            return await call_next(request)
        if extract_guest_token_from_request(request):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Guest portal authentication required"},
            status_code=401,
        )

    return JSONResponse(
        {
            "detail": "Authentication required. Provide a valid private key via Authorization: Bearer, X-Jarvis-Key header, or ?key= query parameter."
        },
        status_code=401,
    )


@app.on_event("startup")
async def startup() -> None:
    app.state.startup_id = str(uuid.uuid4())
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

    QUEUE_WATCHER.start()
    mobile_runtime.start()
    await QUEUE_WATCHER.process_pending()
    try:
        from .tts.warm_start import schedule_tts_warm_start

        schedule_tts_warm_start()
    except Exception:
        logging.debug("TTS warm-start scheduling skipped", exc_info=True)
    asyncio.create_task(_maybe_launch_greeting(app.state.startup_id))


async def _maybe_launch_greeting(startup_id: str) -> None:
    try:
        from .persona.greeting import maybe_send_launch_greeting

        await maybe_send_launch_greeting(startup_id)
    except Exception:
        logging.exception("Launch greeting failed")


@app.on_event("shutdown")
async def shutdown() -> None:
    QUEUE_WATCHER.stop()
    await WHATSAPP_PAIRING.close()
    await mobile_runtime.stop()
    try:
        from .security.hexstrike import HEXSTRIKE

        await HEXSTRIKE.stop()
    except Exception:
        logging.debug("HexStrike shutdown skipped", exc_info=True)


async def _autoload_model(current) -> None:
    try:
        await MANAGER.load(current, preferred_startup_profile(current.inference.profile))
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
