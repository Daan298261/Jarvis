"""Bounded local discovery. An editor/client is never treated as a model server."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Literal

import httpx
import psutil

from ..config import data_dir, load_settings, save_settings
from .backends import inference_headers, parse_models_payload

log = logging.getLogger(__name__)
Action = Literal["use", "leave", "stop", "replace"]
KNOWN_PORTS = {1234, 1235, 8088, 11434, 8000, 30000}
LLAMA_NAMES = {"llama-server", "llama-server.exe"}
SERVER_NAMES = LLAMA_NAMES | {"ollama", "ollama.exe", "lms", "lms.exe"}


def listener_inventory() -> dict[int, dict]:
    """Read only listeners, off the event loop. Never enumerate client secrets."""
    result = {}
    try:
        connections = psutil.net_connections(kind="tcp")
    except (OSError, psutil.Error):
        return result
    for connection in connections:
        if connection.status != psutil.CONN_LISTEN or not connection.pid:
            continue
        if connection.laddr.ip not in {"127.0.0.1", "0.0.0.0", "::", "::1"}:
            continue
        try:
            process = psutil.Process(connection.pid)
            name = process.name().lower()
            if name not in SERVER_NAMES:
                continue
            # Ollama's child llama-server is an implementation detail. Its random
            # port must not become a second offer or an independent stop target.
            if name in LLAMA_NAMES and any(p.name().lower() in {"ollama", "ollama.exe"}
                                          for p in process.parents()):
                continue
            result[connection.laddr.port] = {
                "pid": process.pid, "created": process.create_time(), "name": name,
            }
        except (OSError, psutil.Error):
            continue
    return result


async def optional_metadata(client: httpx.AsyncClient, url: str):
    try:
        response = await client.get(url, timeout=0.4)
        return response.json() if response.is_success else None
    except (httpx.HTTPError, ValueError):
        return None


async def probe(port: int, *, api_key: str = "") -> dict | None:
    """Require actual model metadata, never a successful unrelated health page."""
    base = f"http://127.0.0.1:{port}"
    try:
        async with asyncio.timeout(2.5):
            async with httpx.AsyncClient(timeout=1.0, trust_env=False, follow_redirects=False,
                                         headers=inference_headers(api_key)) as client:
                # Ollama's /v1/models includes unloaded downloads. /api/ps is authoritative.
                body = await optional_metadata(client, base + "/api/ps")
                if isinstance(body, dict) and isinstance(body.get("models"), list):
                    names = parse_models_payload("/api/ps", body)
                    return {"port": port, "backend": "ollama", "models": names, "busy": None} if names else None
                response = await client.get(base + "/v1/models")
                if not response.is_success:
                    return None
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    return None
                names = parse_models_payload("/v1/models", body)
                backend = "remote"
                instances: list[str] = []
                inventory_v1 = await optional_metadata(client, base + "/api/v1/models")
                if isinstance(inventory_v1, dict) and isinstance(inventory_v1.get("models"), list):
                    entries_v1 = inventory_v1["models"]
                    if any(isinstance(item, dict) and "loaded_instances" in item for item in entries_v1):
                        instances = [str(instance["id"]) for item in entries_v1
                                     if isinstance(item, dict) and item.get("type") == "llm"
                                     for instance in item.get("loaded_instances", [])
                                     if isinstance(instance, dict) and instance.get("id")]
                        names = instances
                        backend = "lmstudio"
                # LM Studio can advertise downloaded models through /v1/models.
                # Its native inventory distinguishes the actually loaded instances.
                if backend != "lmstudio":
                    inventory = await optional_metadata(client, base + "/api/v0/models")
                    if isinstance(inventory, dict) and isinstance(inventory.get("data"), list):
                        entries = inventory["data"]
                        if any(isinstance(item, dict) and "state" in item for item in entries):
                            names = [str(item["id"]) for item in entries if isinstance(item, dict)
                                     and item.get("state") == "loaded" and item.get("id")]
                busy = None
                entries = await optional_metadata(client, base + "/slots")
                if isinstance(entries, list) and entries:
                    busy = any(isinstance(item, dict) and item.get("is_processing") for item in entries)
                return {"port": port, "backend": backend, "models": names, "busy": busy,
                        "instance_ids": instances} if names else None
    except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
        return None


def stop_listener(row: dict) -> None:
    """Stop precisely the rediscovered llama listener, not an app/process tree."""
    identity = row.get("process") or {}
    if identity.get("name") not in LLAMA_NAMES:
        raise ValueError("This server cannot be stopped safely by ANZU")
    process = psutil.Process(identity["pid"])
    if process.create_time() != identity["created"] or process.name().lower() != identity["name"]:
        raise ValueError("The server process changed; scan again")
    if not any(c.status == psutil.CONN_LISTEN and c.laddr.port == row["port"]
               for c in process.net_connections(kind="tcp")):
        raise ValueError("The server listener changed; scan again")
    process.terminate()
    try:
        process.wait(timeout=5)
    except psutil.TimeoutExpired as exc:
        raise ValueError("The server did not stop; replacement was not attempted") from exc


async def verify_unloaded(client: httpx.AsyncClient, row: dict) -> None:
    path = "/api/ps" if row["backend"] == "ollama" else "/api/v1/models"
    response = await client.get(f'http://127.0.0.1:{row["port"]}{path}')
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        raise ValueError("Could not verify the model stopped; replacement was not attempted")
    if row["backend"] == "ollama":
        names = parse_models_payload(path, body)
    else:
        names = [str(instance["id"]) for item in body["models"] if isinstance(item, dict)
                 for instance in item.get("loaded_instances", [])
                 if isinstance(instance, dict) and instance.get("id")]
    if row["model"] in names:
        raise ValueError("The model is still loaded; replacement was not attempted")


class RunningModels:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.rows: list[dict] = []
        self.checked_at: float | None = None
        self.error = ""
        self._notified: set[str] = set()
        self._scan_lock = asyncio.Lock()
        self._choice_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def _path(self) -> Path:
        return self.path or data_dir() / "running-model-choices.json"

    def choices(self) -> dict:
        try:
            value = json.loads(self._path().read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}

    def _save(self, choices: dict) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(choices, indent=2), encoding="utf-8")
        temporary.replace(path)

    def snapshot(self) -> dict:
        return {"servers": self.rows, "checked_at": self.checked_at, "error": self.error,
                "running": self._task is not None and not self._task.done()}

    async def scan(self, *, force: bool = False) -> dict:
        async with self._scan_lock:
            if not force and self.checked_at and time.time() - self.checked_at < 15:
                return self.snapshot()
            settings = load_settings()
            from .manager import MANAGER

            inventory = await asyncio.to_thread(listener_inventory)
            ports = sorted(KNOWN_PORTS) + sorted(set(inventory) - KNOWN_PORTS)[:26]
            ports = [p for p in ports if p != settings.front_responder.port
                     and not (MANAGER.state.manages_process and MANAGER.state.pid
                              and p == MANAGER.state.port)]
            results = await asyncio.gather(*[
                probe(p, api_key=settings.inference.api_key if p == settings.inference.port
                      and settings.inference.host in {"127.0.0.1", "localhost"} else "")
                for p in ports
            ])
            choices = await asyncio.to_thread(self.choices)
            rows = []
            for result in results:
                if not result:
                    continue
                for model in result["models"][:32]:
                    identifier = hashlib.sha256(f'{result["port"]}:{model}'.encode()).hexdigest()[:24]
                    process = inventory.get(result["port"])
                    rows.append({
                        **result, "id": identifier, "model": model, "process": process,
                        "base_url": f'http://127.0.0.1:{result["port"]}/v1',
                        "choice": choices.get(identifier),
                        "can_stop": result["backend"] == "ollama" or model in result.get("instance_ids", [])
                                    or bool(process and process["name"] in LLAMA_NAMES),
                        "active": MANAGER.state.loaded and MANAGER.state.port == result["port"]
                                  and MANAGER.state.remote_model == model,
                    })
            self.rows = rows
            self.checked_at = time.time()
            self.error = ""
            return self.snapshot()

    async def decide(self, identifier: str, action: Action) -> dict:
        from .manager import MANAGER
        from ..persona.owner_chat import rebind_owner_conversations_after_hotswap

        async with self._choice_lock:
            prior = next((r for r in self.rows if r["id"] == identifier), None)
            if not prior:
                raise ValueError("That model is no longer available; scan again")
            await self.scan(force=True)
            row = next((r for r in self.rows if r["id"] == identifier), None)
            if not row or row.get("process") != prior.get("process"):
                raise ValueError("The server changed; scan again before choosing")
            if row.get("busy") and action != "leave":
                raise ValueError("Another client is using this model; wait for it to finish")
            choices = await asyncio.to_thread(self.choices)
            settings = load_settings()
            if action == "leave":
                choices[identifier] = "leave"
                await asyncio.to_thread(self._save, choices)
                row["choice"] = "leave"
                # Startup waits for this owner choice instead of competing for VRAM.
                if not MANAGER.state.loaded and settings.inference.auto_load:
                    await MANAGER.load(settings)
                return self.snapshot()
            async with MANAGER._request_lease.exclusive() as acquired:
                if not acquired:
                    raise ValueError("ANZU is answering a request; try again when it finishes")
                before = MANAGER.live_context_size()
                if action in {"stop", "replace"}:
                    if not row["can_stop"]:
                        raise ValueError("This server does not expose a safe stop operation")
                    native_unload = row["backend"] in {"ollama", "lmstudio"}
                    if native_unload:
                        key = settings.inference.api_key if settings.inference.port == row["port"] and settings.inference.host in {"localhost", "127.0.0.1"} else ""
                        async with httpx.AsyncClient(timeout=10, trust_env=False, headers=inference_headers(key)) as client:
                            path = "/api/generate" if row["backend"] == "ollama" else "/api/v1/models/unload"
                            payload = {"model": row["model"], "keep_alive": 0} if row["backend"] == "ollama" else {"instance_id": row["model"]}
                            response = await client.post(f'http://127.0.0.1:{row["port"]}{path}', json=payload)
                            response.raise_for_status()
                            await verify_unloaded(client, row)
                    else:
                        await asyncio.to_thread(stop_listener, row)
                    if row["active"]:
                        await MANAGER.unload()
                        if action == "stop":
                            settings.inference.backend = "llama.cpp"
                            settings.inference.host = "127.0.0.1"
                            settings.inference.port = 8088
                            settings.inference.remote_model = ""
                            settings.inference.api_key = ""
                            await asyncio.to_thread(save_settings, settings)
                    # A multi-model llama server stop dismisses every model on that process.
                    for other in self.rows:
                        if other["id"] == identifier or (not native_unload and other["port"] == row["port"]):
                            choices[other["id"]] = "leave"
                    await asyncio.to_thread(self._save, choices)
                if action in {"use", "replace"}:
                    updated = settings.model_copy(deep=True)
                    if action == "use":
                        updated.inference.backend = row["backend"]
                        updated.inference.host = "127.0.0.1"
                        updated.inference.port = row["port"]
                        updated.inference.remote_model = row["model"]
                        # Never leak another endpoint's credentials to a discovered server.
                        if settings.inference.host not in {"localhost", "127.0.0.1"} or settings.inference.port != row["port"]:
                            updated.inference.api_key = ""
                    else:
                        updated.inference.backend = "llama.cpp"
                        updated.inference.host = "127.0.0.1"
                        updated.inference.port = 8088
                        updated.inference.remote_model = ""
                        updated.inference.api_key = ""
                    try:
                        await MANAGER.load(updated, force=True)
                        await asyncio.to_thread(save_settings, updated)
                    except Exception:
                        # A failed attach must not keep a provider at unsaved settings.
                        await MANAGER.unload()
                        raise
                    rebind_owner_conversations_after_hotswap(
                        context_limit=MANAGER.live_context_size(), previous_context_limit=before,
                    )
                    choices[identifier] = "use" if action == "use" else "leave"
                    await asyncio.to_thread(self._save, choices)
            return await self.scan(force=True)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll(), name="anzu-running-model-discovery")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _poll(self) -> None:
        while True:
            try:
                if self._choice_lock.locked():
                    await asyncio.sleep(1)
                    continue
                await self.scan()
                # Reconnect only the endpoint/model the owner previously selected.
                # Discovery never silently takes over a new server or model.
                from .manager import MANAGER

                settings = load_settings()
                selected = next((r for r in self.rows if r["choice"] == "use"
                                 and r["port"] == settings.inference.port
                                 and r["model"] == settings.inference.remote_model
                                 and settings.inference.host in {"127.0.0.1", "localhost"}), None)
                if selected and not selected.get("busy") and not MANAGER.state.loaded and not MANAGER.state.loading:
                    async with MANAGER._request_lease.exclusive() as acquired:
                        if acquired:
                            await MANAGER.load(settings)
                pending = [r for r in self.rows if not r["choice"] and r["id"] not in self._notified]
                if pending:
                    from ..persona.chat_delivery import publish_owner_text

                    await publish_owner_text(
                        "I found another local model server. Would you like to use it, leave it alone, "
                        "stop it, or replace it with ANZU's model? The choices are on screen.",
                        title="Available local models", source="running_models", lane="front",
                    )
                    self._notified.update(r["id"] for r in pending)
            except Exception as exc:
                self.error = str(exc)[:300]
                log.exception("Running model discovery failed")
            await asyncio.sleep(20)


RUNNING_MODELS = RunningModels()
