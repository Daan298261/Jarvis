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
from .api import advisor, agent_policy, agent_portability, amazon_ads, approvals, auth, automation_breaker, autonomy, coding, companion, computer_use, context_repo, custom_presence, cyber_ato, decision, delegation, diagnostics, guest_portals, help as help_api, hexstrike, ingest, installer, integrations, license, lmstudio, mcp, media, memory, mobile, model, modules, named_personas, owner_chat, packs, perception, perception_commentary, perception_identity, permissions, projects, queue, recovery, runtime_profiles, self_dev, session_personality, settings, setup, supermemory, swarm, system, tasks, tools, trajectories, vault, voice, voice_profiles, worker_environments, workflows
from .auth import authenticate_request, authenticate_websocket
from .guests.service import authenticate_guest_request, extract_guest_token_from_request
from .config import default_allowed_directories, load_settings, logs_dir, repo_root, save_settings
from .db import init_db
from .events import BUS
from .hardware import hardware_dict
from .inference.hotswap import local_lmstudio_fallback_settings
from .inference.manager import MANAGER
from .inference.profiles import preferred_startup_profile
from .integrations.setup import WHATSAPP_PAIRING
from .swarm.capabilities import register_localhost_capabilities
from .swarm.nodes import register_localhost_node
from .swarm.workers import bind_workers_to_node
from .observability.rolling_log import install_rolling_log, record_event
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
    "https://tauri.localhost",
    "http://tauri.localhost",
    "https://asset.localhost",
    "http://asset.localhost",
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
app.include_router(projects.router)
app.include_router(session_personality.router)
app.include_router(named_personas.router)
app.include_router(custom_presence.router)
app.include_router(help_api.router)
app.include_router(voice_profiles.router)
app.include_router(workflows.router)
app.include_router(self_dev.router)
app.include_router(coding.router)
app.include_router(mobile.router)
app.include_router(companion.router)
app.include_router(companion.owner_router)
app.include_router(media.router)
app.include_router(swarm.router)
app.include_router(worker_environments.router)
app.include_router(runtime_profiles.router)
app.include_router(hexstrike.router)
app.include_router(permissions.router)
app.include_router(approvals.router)
app.include_router(computer_use.router)
app.include_router(lmstudio.router)
app.include_router(packs.router)
app.include_router(modules.router)
app.include_router(trajectories.router)
app.include_router(context_repo.router)
app.include_router(supermemory.router)
app.include_router(vault.router)
app.include_router(agent_portability.router)
app.include_router(guest_portals.owner_router)
app.include_router(guest_portals.guest_router)
app.include_router(license.router)
app.include_router(decision.router)
app.include_router(cyber_ato.router)
app.include_router(autonomy.router)
app.include_router(automation_breaker.router)
app.include_router(agent_policy.router)
app.include_router(amazon_ads.router)
app.include_router(setup.router)
app.include_router(integrations.router)
app.include_router(diagnostics.router)
app.include_router(recovery.router)
app.include_router(installer.router)
app.include_router(ingest.router)
app.include_router(perception.router)
app.include_router(perception_commentary.router)
app.include_router(perception_identity.router)
app.include_router(companion_calls_router)
mobile_runtime = MobileRuntime()

frontend_dist = repo_root() / "frontend" / "dist"


@app.middleware("http")
async def rolling_log_http_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        if response.status_code >= 500:
            record_event(
                "http_error",
                message=f"HTTP {response.status_code}",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
        return response
    except Exception as exc:
        record_event(
            "exception",
            message=str(exc),
            source="http",
            method=request.method,
            path=request.url.path,
        )
        raise


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
    try:
        from .recovery.hooks import startup_recovery

        startup_recovery()
    except Exception:
        logging.debug("Recovery journal startup reconcile skipped", exc_info=True)
    try:
        from .agent.durable_execution.recovery import reconcile_execution_on_startup

        await reconcile_execution_on_startup()
    except Exception:
        logging.debug("Execution lease reconcile skipped", exc_info=True)
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    await register_localhost_capabilities(node.id)
    current = load_settings()
    persist_dirs = False
    try:
        from .config import is_ephemeral_workspace_path, settings_path

        raw_path = settings_path()
        if raw_path.exists():
            raw_dirs = json.loads(raw_path.read_text(encoding="utf-8")).get("allowed_directories") or []
            if any(is_ephemeral_workspace_path(str(item)) for item in raw_dirs):
                persist_dirs = True
    except Exception:
        persist_dirs = False
    if not current.allowed_directories:
        current.allowed_directories = default_allowed_directories()
        persist_dirs = True
    if persist_dirs:
        save_settings(current)
    REGISTRY.apply_settings(current)
    try:
        from .auth import ensure_owner_private_key

        ensure_owner_private_key()
    except Exception:
        logging.debug("Owner private key ensure on startup skipped", exc_info=True)
    try:
        from .decision.hooks import register_decision_hooks

        register_decision_hooks()
    except Exception:
        logging.debug("Decision-tier hook registration skipped", exc_info=True)
    logs_dir().mkdir(exist_ok=True)
    install_rolling_log(loop=asyncio.get_running_loop())
    record_event("startup", message="Jarvis backend started", startup_id=app.state.startup_id)
    Path(repo_root() / "data" / "hardware.json").write_text(json.dumps(hardware_dict(), indent=2), encoding="utf-8")
    try:
        from .licensing.clock_log import record_clock_sample

        record_clock_sample()
    except Exception:
        logging.debug("UTC clock log sample skipped", exc_info=True)
    if current.mcp_servers:
        try:
            await MCP.refresh(current.mcp_servers)
        except Exception:
            logging.exception("MCP refresh failed")
    try:
        from .memory.obsidian_vault import bind_vault, ensure_default_vault, public_binding_status

        kv = current.knowledge_vault
        skip_default = os.environ.get("JARVIS_SKIP_DEFAULT_VAULT") == "1" or bool(
            os.environ.get("PYTEST_CURRENT_TEST")
        )
        if skip_default:
            if kv.vault_path.strip() and not public_binding_status().get("bound"):
                bind_vault(kv.vault_path.strip(), init_layout=kv.jarvis_managed_layout)
        else:
            result = ensure_default_vault(
                configured_path=kv.vault_path.strip(),
                init_layout=kv.jarvis_managed_layout or not kv.vault_path.strip(),
            )
            bound_path = str(result.get("vault_path") or "").strip()
            if bound_path and (
                current.knowledge_vault.vault_path != bound_path
                or not current.knowledge_vault.jarvis_managed_layout
            ):
                current.knowledge_vault.vault_path = bound_path
                current.knowledge_vault.jarvis_managed_layout = True
                if bound_path not in current.allowed_directories:
                    current.allowed_directories.append(bound_path)
                save_settings(current)
    except Exception:
        logging.debug("Vault bind on startup skipped", exc_info=True)
    try:
        asyncio.create_task(_auto_start_supermemory_and_refresh_node(node.id))
        asyncio.create_task(_auto_start_crucix())
    except Exception:
        logging.debug("Supermemory auto-start scheduling skipped", exc_info=True)
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
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from .persona.named_persona import reapply_stored_main_persona

            reapply_stored_main_persona()
            from .presence.custom_ui import reapply_stored_custom_presence

            reapply_stored_custom_presence()
        except Exception:
            logging.debug("Named persona reapply skipped", exc_info=True)
    asyncio.create_task(_maybe_launch_greeting(app.state.startup_id))
    asyncio.create_task(_maybe_notify_health())


async def _maybe_notify_health() -> None:
    try:
        from .systems.health_notify import maybe_notify_health

        await maybe_notify_health()
    except Exception:
        logging.exception("Health notify failed")


async def _maybe_launch_greeting(startup_id: str) -> None:
    try:
        from .persona.greeting import maybe_send_launch_greeting

        await maybe_send_launch_greeting(startup_id)
    except Exception:
        logging.exception("Launch greeting failed")


async def _auto_start_supermemory_and_refresh_node(node_id: str) -> None:
    """Start the private sidecar after Jarvis starts, then refresh node inventory."""
    try:
        from .modules.supermemory_runtime import auto_start as auto_start_supermemory

        await auto_start_supermemory()
    except Exception:
        logging.exception("Supermemory auto-start failed")
    finally:
        try:
            await bind_workers_to_node(node_id)
            await register_localhost_capabilities(node_id)
        except Exception:
            logging.debug("Supermemory node registration refresh skipped", exc_info=True)


async def _auto_start_crucix() -> None:
    try:
        from .modules.crucix_runtime import auto_start as auto_start_crucix
        await auto_start_crucix()
    except Exception:
        logging.exception("Crucix auto-start failed")


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
    try:
        from .modules.supermemory_runtime import shutdown as shutdown_supermemory
        await shutdown_supermemory()
    except Exception:
        logging.debug("Supermemory shutdown skipped", exc_info=True)
    try:
        from .modules.crucix_runtime import shutdown as shutdown_crucix
        await shutdown_crucix()
    except Exception:
        logging.debug("Crucix shutdown skipped", exc_info=True)


async def _autoload_model(current) -> None:
    try:
        await MANAGER.load(current, preferred_startup_profile(current.inference.profile))
    except Exception:
        fallback = local_lmstudio_fallback_settings(current)
        if fallback is None:
            logging.exception("Model auto-load failed; it can be loaded from the Model page")
            return
        try:
            profile = preferred_startup_profile(fallback.inference.profile)
            await MANAGER.load(fallback, profile)
        except Exception:
            logging.exception("LM Studio was unavailable and local fallback failed")
            return
        fallback.inference.profile = profile
        save_settings(fallback)
        logging.warning(
            "LM Studio was unavailable at startup; switched to Jarvis-managed local profile %s",
            profile,
        )


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
