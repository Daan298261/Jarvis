"""Bounded local discovery. An editor/client is never treated as a model server."""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import socket
import subprocess
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import psutil

from ..config import data_dir, load_settings, save_settings
from .backends import inference_headers, parse_models_payload
from .idle_unload import IDLE_UNLOAD
from .keep_alive import is_denied, lmstudio_ttl_seconds, note_ollama_ps, ollama_pinned, ollama_request
from .loaded_models import LLAMA_SERVER, LMSTUDIO, LOADED, OLLAMA
from .model_launch import ModelStart, launch_profiles, budget_check, vram_snapshot

log = logging.getLogger(__name__)
Action = Literal["use", "leave", "stop", "replace"]
KNOWN_PORTS = {1234, 1235, 8080, 8088, 11434, 8000, 5000, 5001, 30000}
LLAMA_NAMES = {"llama-server", "llama-server.exe"}
LOAD_TIMEOUT_SECONDS = 600.0
CLIENT_NAMES = {"cursor", "codex", "aider", "antigravity", "chatgpt"}


def is_client_process(name: str) -> bool:
    name = name.casefold().removesuffix(".exe")
    return name in CLIENT_NAMES or any(name.startswith(prefix + "-") for prefix in CLIENT_NAMES)


def process_kind(name: str, command: list[str] | None = None) -> str | None:
    """Classify servers, never editors; Python requires an explicit server module."""
    name = name.casefold().removesuffix(".exe")
    if is_client_process(name):
        return None
    kinds = {"ollama": "ollama", "lms": "lmstudio", "lm studio": "lmstudio",
             "lm-studio": "lmstudio", "llama-server": "llama.cpp", "vllm": "vllm",
             "koboldcpp": "koboldcpp", "text-generation-webui": "textgen",
             "oobabooga": "textgen", "colibri": "colibri", "sglang": "sglang"}
    if name in kinds:
        return kinds[name]
    if name.startswith("python"):
        text = " ".join(command or []).lower().replace("\\", "/")
        for marker, kind in (("vllm.entrypoints", "vllm"), ("sglang.launch_server", "sglang"),
                             ("koboldcpp.py", "koboldcpp"), ("text-generation-webui/", "textgen"),
                             ("oobabooga/", "textgen"), ("colibri", "colibri")):
            if marker in text:
                return kind
    return None


def port_in_use(port: int) -> bool:
    """Binding also detects IPv6/wildcard listeners; a failed API is no license to spawn."""
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind((address, port))
        except OSError as exc:
            if family == socket.AF_INET6 and exc.errno in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
                continue
            return True
    return False


def ollama_serves() -> list[dict]:
    rows = []
    try:
        for process in psutil.process_iter(["pid", "name"]):
            try:
                info = process.info
                if str(info.get("name", "")).lower() in {"ollama", "ollama.exe"} and "serve" in process.cmdline():
                    rows.append({"pid": info["pid"], "created": process.create_time()})
            except (OSError, psutil.Error):
                continue
    except (OSError, psutil.Error):
        pass
    return rows


def _ancestor_names(pid: int) -> list[tuple[int, str]]:
    chain, seen = [], set()
    try:
        current = psutil.Process(pid).ppid()
        while current and current not in seen and len(chain) < 8:
            seen.add(current)
            process = psutil.Process(current)
            chain.append((current, process.name().lower()))
            current = process.ppid()
    except (OSError, psutil.Error):
        pass
    return chain


def ollama_diagnostics(serves: list[dict], listener: dict | None = None) -> list[str]:
    """Owner-facing explanation of a competing tray server; never changes autostart."""
    from .ollama_runtime import TRAY_APP_NAMES, ollama_autostart, ollama_port_conflict, ollama_tray_running
    notes = []
    tray = ollama_tray_running()
    pid = (listener or {}).get("pid")
    if tray and pid and str((listener or {}).get("name", "")).startswith("ollama"):
        ancestors = _ancestor_names(int(pid))
        if ancestors and not any(name in TRAY_APP_NAMES for _, name in ancestors):
            parent_pid, parent = ancestors[0]
            notes.append(f"The Ollama server on 11434 (PID {pid}) was started by {parent} (PID {parent_pid}), "
                         f"not by the Ollama tray app (PID {', '.join(map(str, tray))}), so the tray app cannot "
                         "run its own server and retries against the busy port. ANZU keeps using the running "
                         "server and, after this fix, starts Ollama through the tray app. To clear it once: quit "
                         f"Ollama from the tray, end PID {pid}, then start Ollama from the Start menu.")
    conflict = ollama_port_conflict()
    if conflict:
        notes.append(
            "Ollama's tray app keeps retrying to start a second server because port 11434 is already held"
            + (f" (serve PIDs {', '.join(str(p['pid']) for p in serves)})" if serves else "")
            + f"; {conflict['recent_conflicts']} bind errors in the last log tail, server.log is "
            f"{conflict['log_bytes'] // (1024 * 1024)} MB. ANZU will not start another server. "
            "Fix: quit Ollama from the tray"
            + (" (tray PIDs " + ", ".join(map(str, tray)) + ")" if tray else "")
            + ", end the other Ollama server, then start Ollama from the Start menu.")
    autostart = ollama_autostart()
    if autostart and not tray and serves:
        notes.append("Ollama is set to start at login (" + "; ".join(autostart)
                     + ") but its tray app is not running; another Ollama server owns the port.")
    return notes


def audit_control(action: str, *, ok: bool | None = None, detail: dict | None = None) -> None:
    from ..manager import debug_log
    debug_log.write("WARNING" if ok is False else "INFO", "control_start" if ok is None else "control_end",
                    action="model_" + action, ok=ok, detail=detail)


async def run_lms(args: list[str], *, timeout: float = 120) -> None:
    from .lmstudio_server import lmstudio_cli
    binary = await asyncio.to_thread(lmstudio_cli)
    if not binary:
        raise ValueError("LM Studio CLI (lms) was not found")
    completed = await asyncio.to_thread(subprocess.run, [binary, *args],
        capture_output=True, text=True, timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise ValueError("LM Studio command failed: " + (completed.stderr or completed.stdout)[:300])


async def unload_native(row: dict) -> None:
    """The one native unload (Manager Stop, offline stop); unload-all releases through the same verify."""
    if is_denied(row["model"]):
        raise ValueError("ANZU never stops this model")
    settings = await asyncio.to_thread(load_settings)
    key = settings.inference.api_key if settings.inference.port == row["port"] and settings.inference.host in {"localhost", "127.0.0.1", "::1"} else ""
    base = row.get("base_url", f"http://127.0.0.1:{row['port']}/v1").removesuffix("/v1")
    async with httpx.AsyncClient(timeout=15, trust_env=False, headers=inference_headers(key)) as client:
        if row["backend"] == "lmstudio":
            # Modern instances can be unloaded through the native API; v0 uses lms.
            if row["model"] in row.get("instance_ids", []):
                response = await client.post(base + "/api/v1/models/unload", json={"instance_id": row["model"]})
                response.raise_for_status()
            elif row["port"] == 1234:
                await run_lms(["unload", row["model"]])
            else:
                raise ValueError("No safe unload operation for this LM Studio instance")
        else:
            # keep_alive 0 comes from the one keep-alive helper (RFC-0242), never spelled here.
            url = urlparse(base)
            response = await ollama_request(client, url.hostname or "127.0.0.1", url.port or row["port"],
                                            "/api/generate", row["model"], release=True)
            response.raise_for_status()
        await verify_unloaded(client, row)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


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
            if is_client_process(name):
                result[connection.laddr.port] = {"excluded": True}
                continue
            # Ollama's child llama-server is an implementation detail. Its random
            # port must not become a second offer or an independent stop target.
            if name in LLAMA_NAMES and any(p.name().lower() in {"ollama", "ollama.exe"}
                                          for p in process.parents()):
                continue
            if name in {"ollama", "ollama.exe"} and any(arg in {"runner", "--runner"} for arg in process.cmdline()):
                continue
            result[connection.laddr.port] = {
                "pid": process.pid, "created": process.create_time(), "name": name,
                "kind": process_kind(name, process.cmdline() if name.startswith("python") else None),
                "host": "::1" if ":" in connection.laddr.ip else "127.0.0.1",
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


async def probe(port: int, *, api_key: str = "", host: str = "127.0.0.1", include_embeddings: bool = False,
                client: httpx.AsyncClient | None = None, include_available: bool = False) -> dict | None:
    """Require actual model metadata, never a successful unrelated health page."""
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Discovery probes are loopback only")
    base = f"http://{'[::1]' if host == '::1' else host}:{port}"
    try:
        async with asyncio.timeout(2.5):
            async with AsyncExitStack() as stack:
                client = client or await stack.enter_async_context(httpx.AsyncClient(
                    timeout=1.0, trust_env=False, follow_redirects=False, headers=inference_headers(api_key)))
                # Ollama's /v1/models includes unloaded downloads. /api/ps is authoritative.
                body = await optional_metadata(client, base + "/api/ps")
                if isinstance(body, dict) and isinstance(body.get("models"), list):
                    names = parse_models_payload("/api/ps", body)
                    metadata = {str(item.get("name") or item.get("model")): {
                        "display_name": str(item.get("name") or item.get("model")),
                        "size_bytes": item.get("size"), "context_size": item.get("context_length"),
                        "vram_bytes": item.get("size_vram"),
                        "expires_at": item.get("expires_at"), "pinned": ollama_pinned(item.get("expires_at")),
                        "parameters": _mapping(item.get("details")).get("parameter_size"),
                        "quantization": _mapping(item.get("details")).get("quantization_level"),
                    } for item in body["models"] if isinstance(item, dict)}
                    available = []
                    if include_available:
                        tags = _mapping(await optional_metadata(client, base + "/api/tags"))
                        available = [item for item in tags.get("models", []) if isinstance(item, dict)
                                     and isinstance(item.get("name"), str)] if isinstance(tags.get("models"), list) else []
                    return {"port": port, "backend": "ollama", "models": names, "busy": None,
                            "available_models": available, "verified_loaded": True,
                            "source": "ollama_ps", "metadata": metadata} if names or include_available else None
                response = await client.get(base + "/v1/models")
                if not response.is_success:
                    return None
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    return None
                names = parse_models_payload("/v1/models", body)
                backend = "remote"
                verified_loaded = False
                source = "openai_advertised"
                metadata = {str(item["id"]): {
                    "display_name": str(item["id"]), "context_size": item.get("max_model_len") or item.get("context_length"),
                    "size_bytes": item.get("size_bytes"),
                } for item in body["data"] if isinstance(item, dict) and item.get("id")}
                available = []
                instances: list[str] = []
                inventory_v1 = await optional_metadata(client, base + "/api/v1/models")
                if isinstance(inventory_v1, dict) and isinstance(inventory_v1.get("models"), list):
                    entries_v1 = inventory_v1["models"]
                    if any(isinstance(item, dict) and "loaded_instances" in item for item in entries_v1):
                        instances = [str(instance["id"]) for item in entries_v1
                                     if isinstance(item, dict) and item.get("type") in ({"llm", "embedding"} if include_embeddings else {"llm"})
                                     for instance in (item.get("loaded_instances") or [])
                                     if isinstance(instance, dict) and instance.get("id")]
                        names = instances
                        backend = "lmstudio"
                        verified_loaded = True
                        source = "lmstudio_loaded_instances"
                        available = [dict(item, name=item.get("key")) for item in entries_v1
                                     if isinstance(item, dict) and item.get("type") == "llm" and item.get("key")]
                        metadata = {str(instance["id"]): {
                            "display_name": str(item.get("display_name") or item.get("key") or instance["id"]),
                            "model_key": item.get("key"), "parameters": item.get("params_string"),
                            "quantization": _mapping(item.get("quantization")).get("name") or (item.get("quantization") if isinstance(item.get("quantization"), str) else None),
                            "size_bytes": item.get("size_bytes"),
                            "context_size": _mapping(instance.get("config")).get("context_length"),
                        } for item in entries_v1 if isinstance(item, dict) and item.get("type") in ({"llm", "embedding"} if include_embeddings else {"llm"})
                            for instance in (item.get("loaded_instances") or [])
                            if isinstance(instance, dict) and instance.get("id")}
                # LM Studio can advertise downloaded models through /v1/models.
                # Its native inventory distinguishes the actually loaded instances.
                if backend != "lmstudio":
                    inventory = await optional_metadata(client, base + "/api/v0/models")
                    if isinstance(inventory, dict) and isinstance(inventory.get("data"), list):
                        entries = inventory["data"]
                        if any(isinstance(item, dict) and "state" in item for item in entries):
                            names = [str(item["id"]) for item in entries if isinstance(item, dict)
                                     and item.get("state") == "loaded" and item.get("id")]
                            verified_loaded = True
                            backend = "lmstudio"
                            available = [dict(item, name=item["id"]) for item in entries
                                         if isinstance(item, dict) and item.get("id")]
                            metadata = {str(item["id"]): {"display_name": item["id"],
                                "context_size": item.get("loaded_context_length"), "size_bytes": item.get("size_bytes"),
                                "parameters": item.get("params_string"), "quantization": item.get("quantization")}
                                for item in entries if isinstance(item, dict) and item.get("id") and item.get("state") == "loaded"}
                            source = "lmstudio_v0_loaded"
                if (include_embeddings or include_available) and not verified_loaded:
                    props = await optional_metadata(client, base + "/props")
                    if isinstance(props, dict) and props.get("model_path") and props.get("total_slots"):
                        health = await optional_metadata(client, base + "/health")
                        if isinstance(health, dict) and health.get("status") == "ok":
                            name = str(props.get("model_alias") or props["model_path"])
                            names = [name]
                            backend, source, verified_loaded = "llama.cpp", "llama_props_ready", True
                            metadata = {name: {"display_name": str(props["model_path"]).replace("\\", "/").split("/")[-1],
                                "model_key": props["model_path"],
                                "context_size": _mapping(props.get("default_generation_settings")).get("n_ctx")}}
                busy = None
                entries = await optional_metadata(client, base + "/slots")
                if isinstance(entries, list) and entries:
                    busy = any(isinstance(item, dict) and item.get("is_processing") for item in entries)
                return {"port": port, "backend": backend, "models": names, "busy": busy,
                        "available_models": available,
                        "instance_ids": instances, "verified_loaded": verified_loaded,
                        "source": source, "metadata": metadata} if names or (include_available and (available or backend == "lmstudio")) else None
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
    except psutil.TimeoutExpired:
        # Recheck identity immediately before escalation; never kill a reused PID.
        if process.create_time() != identity["created"] or process.name().lower() != identity["name"]:
            raise ValueError("The server process changed before forced stop")
        process.kill()
        process.wait(timeout=5)


async def verify_unloaded(client: httpx.AsyncClient, row: dict) -> None:
    legacy_lms = row["backend"] == "lmstudio" and row.get("source") == "lmstudio_v0_loaded"
    path = "/api/ps" if row["backend"] == "ollama" else "/api/v0/models" if legacy_lms else "/api/v1/models"
    base = row.get("base_url", f"http://127.0.0.1:{row['port']}/v1").removesuffix("/v1")
    response = await client.get(base + path)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data" if legacy_lms else "models"), list):
        raise ValueError("Could not verify the model stopped; replacement was not attempted")
    if row["backend"] == "ollama":
        names = parse_models_payload(path, body)
    elif legacy_lms:
        names = [item.get("id") for item in body["data"] if isinstance(item, dict) and item.get("state") == "loaded"]
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
        self.inventory: list[dict] = []
        self.diagnostics: list[str] = []
        self._launched: dict[int, dict] = {}
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
                "inventory": self.inventory, "diagnostics": self.diagnostics,
                "running": self._task is not None and not self._task.done()}

    async def profiles(self) -> dict:
        return {"profiles": await asyncio.to_thread(launch_profiles, self.inventory)}

    async def start_model(self, body: ModelStart, *, preview: bool = False) -> dict:
        """Explicit owner Start; shares choice serialization and the inference lease."""
        from .manager import MANAGER
        if not preview and not body.confirm:
            raise ValueError("Explicit confirmation is required to start a model")
        audit_control("start", detail={"profile": body.profile_id, "preview": preview})
        try:
            async with self._choice_lock:
                async with MANAGER._request_lease.exclusive() as acquired:
                    if not acquired:
                        raise ValueError("ANZU is answering a request; try again when it finishes")
                    await self.scan(force=True)
                    profiles = (await self.profiles())["profiles"]
                    profile = next((p for p in profiles if p["id"] == body.profile_id), None)
                    if profile is None:
                        raise ValueError("Launch profile is no longer available; scan again")
                    if is_denied(profile["model"]):
                        raise ValueError("ANZU never starts this model")
                    settings = await asyncio.to_thread(load_settings)
                    if profile["port"] == settings.front_responder.port or (
                        MANAGER.state.manages_process and profile["port"] == MANAGER.state.port
                    ):
                        raise ValueError("This port belongs to ANZU's worker/front seat")
                    report = budget_check(profile, body, await asyncio.to_thread(vram_snapshot))
                    report["profile"] = profile
                    report["server_restart_required"] = profile["backend"] == "ollama" and (
                        body.kv_cache != "server" or body.flash_attention != "server")
                    if preview:
                        audit_control("start", ok=True, detail={"profile": body.profile_id, "preview": True})
                        return report
                    if report["requires_confirmation"] and not body.confirm_over_budget:
                        raise ValueError("VRAM budget exceeded or unknown; review /running/start/preview and explicitly confirm_over_budget")
                    # An owner Start is an explicit Load (RFC-0242): it lifts an earlier Unload hold.
                    IDLE_UNLOAD.explicit_load()
                    await self._launch_profile(profile, body, report["context_size"])
                    self._record_started(profile)
                    result = await self.scan(force=True)
                    result["start"] = {"profile_id": body.profile_id, "model": profile["model"], "budget": report}
            audit_control("start", ok=True, detail={"profile": body.profile_id})
            return result
        except Exception as exc:
            audit_control("start", ok=False, detail={"profile": body.profile_id, "error": str(exc)[:300]})
            raise

    def _record_started(self, profile: dict) -> None:
        """A successful Start is an ANZU load: one ledger entry (RFC-0242 ``LOADED``), so Unload-all and the idle
        timer release it. A Manager-spawned llama-server has no per-turn use clock, so only an owner Unload stops it."""
        backend = {"ollama": OLLAMA, "lmstudio": LMSTUDIO, "llama.cpp": LLAMA_SERVER}[profile["backend"]]
        LOADED.record(backend, profile["model"], port=int(profile["port"]), idle_policy=backend != LLAMA_SERVER)

    async def release_launched(self, port: int) -> None:
        """Stop the llama-server this manager's Start spawned on ``port`` (Unload-all / Stop).

        Only the process recorded at spawn is stopped, after the same PID / create-time / listener check
        as a Stop; a process that is already gone just leaves the record. Raises when it cannot be stopped.
        """
        identity = self._launched.get(port)
        if not identity:
            return
        listener = (await asyncio.to_thread(listener_inventory)).get(port) or {}
        if all(listener.get(k) == identity.get(k) for k in ("pid", "created")):
            await asyncio.to_thread(stop_listener, {"port": port, "process": listener})
        else:
            def same_process_alive() -> bool:
                try:
                    return psutil.Process(identity["pid"]).create_time() == identity["created"]
                except (psutil.Error, OSError):
                    return False
            if await asyncio.to_thread(same_process_alive):
                raise ValueError(f"ANZU's llama-server on port {port} no longer answers there; it was not stopped")
        self._launched.pop(port, None)

    def _forget_stopped(self, row: dict) -> None:
        """A verified Stop: the ledger no longer lists what it stopped (a single source of truth)."""
        if row["backend"] in {OLLAMA, LMSTUDIO}:
            meta = (row.get("metadata") or {}).get(row["model"]) or {}
            entry = LOADED.match(row["backend"], [row["model"], str(meta.get("model_key") or "")])
            if entry is not None:
                LOADED.forget(entry)
            return
        self._launched.pop(row["port"], None)
        for entry in LOADED.entries():
            if entry.backend == LLAMA_SERVER and entry.port == row["port"]:
                LOADED.forget(entry)

    async def _launch_profile(self, profile: dict, body: ModelStart, context: int) -> None:
        port, backend = profile["port"], profile["backend"]
        server = next((s for s in self.inventory if s["port"] == port), None)
        used = await asyncio.to_thread(port_in_use, port)
        if body.kv_cache in {"q8_0", "q4_0"} and body.flash_attention == "off":
            raise ValueError("Quantized KV cache requires flash attention on")
        if body.n_cpu_moe is not None and (backend != "llama.cpp" or profile.get("n_cpu_moe") is None):
            raise ValueError("CPU expert offload is available only for a configured MoE llama-server profile")
        if server and server["backend"] != backend:
            raise ValueError("Target port belongs to a different model server; choose another port")
        if used and not server:
            raise ValueError("Target port is already in use; duplicate server launch refused")
        if backend == "ollama":
            if server and (body.kv_cache != "server" or body.flash_attention != "server"):
                # These are SERVER settings, not generate options. Reading just these
                # two keys never exposes other process environment variables.
                identity = server.get("process") or {}
                def server_options():
                    try:
                        process = psutil.Process(identity["pid"])
                        if process.create_time() != identity["created"]:
                            return {}
                        env = process.environ()
                        return {k: env.get(k) for k in ("OLLAMA_KV_CACHE_TYPE", "OLLAMA_FLASH_ATTENTION")}
                    except (KeyError, psutil.Error, OSError):
                        return {}
                options = await asyncio.to_thread(server_options)
                desired = {}
                if body.kv_cache != "server":
                    desired["OLLAMA_KV_CACHE_TYPE"] = body.kv_cache
                if body.flash_attention != "server" or body.kv_cache in {"q8_0", "q4_0"}:
                    desired["OLLAMA_FLASH_ATTENTION"] = "0" if body.flash_attention == "off" else "1"
                if any(options.get(k) != v for k, v in desired.items()):
                    raise ValueError("Ollama server restart required for these cache/flash settings; ANZU will not restart the owner's server. Choose server settings or configure and restart it yourself.")
            if not server:
                from .ollama_runtime import _start_server
                if await asyncio.to_thread(ollama_serves):
                    raise ValueError("An ollama serve process already exists; duplicate server launch refused")
                env = {}
                if body.kv_cache != "server":
                    env["OLLAMA_KV_CACHE_TYPE"] = body.kv_cache
                if body.flash_attention != "server" or body.kv_cache in {"q8_0", "q4_0"}:
                    env["OLLAMA_FLASH_ATTENTION"] = "0" if body.flash_attention == "off" else "1"
                from .ollama_runtime import OllamaAlreadyRunning
                try:
                    await asyncio.to_thread(_start_server, "127.0.0.1", port, env_overrides=env)
                except OllamaAlreadyRunning:
                    if env:
                        raise ValueError("An Ollama tray app/server is already starting; its cache/flash settings "
                                         "cannot be changed by ANZU. Choose server settings or restart it yourself.") from None
                # Adopt the tray app's (or our) server once it answers.
                server = await self._wait_server(port, "ollama", timeout=60)
            from .ollama_runtime import _model_present
            available = [p.get("name") for p in server.get("available_models", [])]
            if not _model_present(available, profile["model"]):
                raise ValueError("This Ollama model is not downloaded. Pull it explicitly before Start.")
            settings = await asyncio.to_thread(load_settings)
            key = settings.inference.api_key if settings.inference.port == port and settings.inference.host in {"localhost", "127.0.0.1", "::1"} else ""
            async with httpx.AsyncClient(timeout=LOAD_TIMEOUT_SECONDS, trust_env=False, headers=inference_headers(key)) as client:
                # keep_alive from the one helper: "300s" with Keep warm off, "-1" with it on.
                endpoint = urlparse(server["endpoint"])
                response = await ollama_request(client, endpoint.hostname or "127.0.0.1", endpoint.port or port,
                                                "/api/generate", profile["model"],
                                                {"prompt": "", "stream": False, "options": {"num_ctx": context}})
                response.raise_for_status()
            await self._wait_server(port, backend, profile["model"])
        elif backend == "lmstudio":
            if body.kv_cache != "server" or body.flash_attention != "server" or body.n_cpu_moe is not None:
                raise ValueError("LM Studio cache/flash settings must be configured in LM Studio")
            if not server:
                await run_lms(["server", "start", "--port", str(port)])
            seconds = lmstudio_ttl_seconds(model=profile["model"])  # 300 with Keep warm off, none with it on
            ttl = ["--ttl", str(seconds)] if seconds is not None else []
            await run_lms(["load", profile["model"], "--context-length", str(context), "-y", *ttl], timeout=LOAD_TIMEOUT_SECONDS)
            await self._wait_server(port, backend, profile["model"])
        elif backend == "llama.cpp":
            if used or server:
                raise ValueError("Target port is already in use; duplicate server launch refused")
            kv = body.kv_cache if body.kv_cache != "server" else "q8_0"
            flash = body.flash_attention if body.flash_attention != "server" else "on"
            args = [profile["binary"], "--model", profile["model"], "--host", "127.0.0.1", "--port", str(port),
                    "--ctx-size", str(context), "--cache-type-k", kv, "--cache-type-v", kv,
                    "--flash-attn", flash, "--jinja", "--n-gpu-layers", "99"]
            moe = body.n_cpu_moe if body.n_cpu_moe is not None else profile.get("n_cpu_moe")
            if moe is not None:
                args.extend(["--n-cpu-moe", str(moe)])
            def spawn():
                from ..config import logs_dir
                with (logs_dir() / "model-launch.log").open("ab") as handle:
                    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return process, {"pid": process.pid, "created": psutil.Process(process.pid).create_time()}
            process, identity = await asyncio.to_thread(spawn)
            self._launched[port] = identity
            try:
                # A 27B/35B GGUF needs minutes to map from disk (MoE weights mostly in RAM).
                await self._wait_server(port, backend, timeout=LOAD_TIMEOUT_SECONDS)
            except BaseException:
                # This handle belongs exclusively to the child just spawned here.
                # Failed readiness must not leave an unreachable model consuming VRAM.
                def cleanup():
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                await asyncio.to_thread(cleanup)
                self._launched.pop(port, None)
                raise
        else:
            raise ValueError("Unsupported launch backend")

    async def _wait_server(self, port: int, backend: str, model: str | None = None,
                           timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        existing = next((s for s in self.inventory if s["port"] == port), {})
        host = "::1" if "[::1]" in existing.get("endpoint", "") else "127.0.0.1"
        base = f"http://{'[::1]' if host == '::1' else host}:{port}"
        settings = await asyncio.to_thread(load_settings)
        key = settings.inference.api_key if settings.inference.port == port and settings.inference.host in {"localhost", "127.0.0.1", "::1"} else ""
        while time.monotonic() < deadline:
            row = await probe(port, host=host, api_key=key, include_available=True)
            from .ollama_runtime import _model_present
            if row and row["backend"] == backend and (model is None or (backend == "ollama" and _model_present(row["models"], model)) or model in row["models"] or any(
                m.get("model_key") == model for m in row.get("metadata", {}).values())):
                return {**row, "endpoint": base}
            await asyncio.sleep(.5)
        raise ValueError("Server/model did not become ready; inspect model-launch.log or the backend's logs")

    async def stop_offline(self, identifier: str, *, confirm: bool,
                           core_absent: Callable[[], Awaitable[bool]]) -> dict:
        """Manager-only fallback, after Manager independently proves core absence."""
        if not confirm:
            raise ValueError("Explicit confirmation is required")
        async with self._choice_lock:
            prior = next((r for r in self.rows if r["id"] == identifier), None)
            await self.scan(force=True)
            row = next((r for r in self.rows if r["id"] == identifier), None)
            if not prior or not row or prior.get("process") != row.get("process"):
                raise ValueError("The server changed; scan again")
            if row["backend"] not in {"ollama", "lmstudio"} or row.get("busy"):
                raise ValueError("Only idle Ollama/LM Studio unload is available while the core is down")
            if not await core_absent():
                raise ValueError("Core may have started; no offline stop attempted")
            audit_control("stop", detail={"model": row["model"], "core": "down"})
            try:
                await unload_native(row)
            except Exception as exc:
                audit_control("stop", ok=False, detail={"error": str(exc)[:300]})
                raise
            audit_control("stop", ok=True, detail={"model": row["model"]})
            return await self.scan(force=True)

    async def scan(self, *, force: bool = False) -> dict:
        async with self._scan_lock:
            if not force and self.checked_at and time.time() - self.checked_at < 15:
                return self.snapshot()
            settings = await asyncio.to_thread(load_settings)
            from .manager import MANAGER

            try:
                inventory, serves = await asyncio.wait_for(asyncio.gather(
                    asyncio.to_thread(listener_inventory), asyncio.to_thread(ollama_serves)), timeout=3)
            except TimeoutError:
                inventory, serves = {}, []
                self.diagnostics = ["Process scan timed out; only known ports were probed."]
            else:
                self.diagnostics = []
            if len(serves) > 1:
                self.diagnostics.append("Competing ollama serve processes detected: " + ", ".join(str(p["pid"]) for p in serves))
            try:
                self.diagnostics += await asyncio.wait_for(asyncio.to_thread(ollama_diagnostics, serves, inventory.get(11434)), timeout=3)
            except (TimeoutError, OSError, psutil.Error) as exc:
                log.debug("ollama diagnostics unavailable: %s", exc)
            configured = {settings.inference.port} if settings.inference.host in {"127.0.0.1", "localhost", "::1"} else set()
            ports = sorted(KNOWN_PORTS | configured) + sorted(set(inventory) - KNOWN_PORTS - configured)[:54]
            ports = [p for p in ports if p != settings.front_responder.port
                     and not inventory.get(p, {}).get("excluded")
                     and not (MANAGER.state.manages_process and MANAGER.state.pid
                              and p == MANAGER.state.port)]
            if len(inventory) > 54:
                self.diagnostics.append("Listener scan capped at 64 ports; coverage may be incomplete.")
            async def inspect_all():
                async with httpx.AsyncClient(timeout=1, trust_env=False, follow_redirects=False) as client:
                    return await asyncio.gather(*[
                        probe(p, api_key=settings.inference.api_key if p == settings.inference.port
                              and settings.inference.host in {"127.0.0.1", "localhost", "::1"} else "",
                              host=inventory.get(p, {}).get("host", "127.0.0.1"), include_available=True,
                              client=None if p == settings.inference.port and settings.inference.api_key else client)
                        for p in ports])
            # HTTP/TLS initialization and metadata decoding must not starve health/chat.
            results = await asyncio.to_thread(lambda: asyncio.run(inspect_all()))
            choices = await asyncio.to_thread(self.choices)
            rows = []
            self.inventory = []
            for result in results:
                if not result:
                    continue
                if result.get("source") == "ollama_ps":  # a full /api/ps listing: refresh the owner pins (keep_alive.py)
                    note_ollama_ps(result["port"], [{"name": name, "expires_at": meta.get("expires_at")}
                                                    for name, meta in result["metadata"].items()])
                process = inventory.get(result["port"])
                host = (process or {}).get("host", "127.0.0.1")
                base = f"http://{'[::1]' if host == '::1' else host}:{result['port']}"
                kind = (process or {}).get("kind") or result["backend"]
                # kind is presentation metadata; unknown OpenAI servers still use the existing remote provider.
                launched = self._launched.get(result["port"], {})
                owner = "anzu-managed" if process and launched and all(process.get(k) == launched.get(k) for k in ("pid", "created")) else "external"
                self.inventory.append({**result, "kind": kind, "endpoint": base, "process": process,
                                       "pid": (process or {}).get("pid"), "owner": owner})
                for model in result["models"][:32]:
                    identifier = hashlib.sha256(f'{result["port"]}:{model}'.encode()).hexdigest()[:24]
                    process = inventory.get(result["port"])
                    rows.append({
                        **result, "id": identifier, "model": model, "process": process,
                        "base_url": base + "/v1", "host": host, "owner": owner, "kind": kind,
                        "choice": choices.get(identifier) or (
                            "use" if settings.inference.backend not in {"llama.cpp", "local"}
                            and settings.inference.host in {"127.0.0.1", "localhost"}
                            and settings.inference.port == result["port"]
                            and settings.inference.remote_model == model else None
                        ),
                        "can_stop": result["backend"] == "ollama" or (result["backend"] == "lmstudio" and result["port"] == 1234) or model in result.get("instance_ids", [])
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
        from ..engine_mode import require_model, model_enabled
        if action in {"use", "replace"}:
            require_model(load_settings())
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
                if (model_enabled(settings) and not MANAGER.state.loaded and not MANAGER.state.loading
                        and settings.inference.auto_load and not IDLE_UNLOAD.background_blocked()):
                    await MANAGER.load(settings)
                return self.snapshot()
            async with MANAGER._request_lease.exclusive() as acquired:
                if not acquired:
                    raise ValueError("ANZU is answering a request; try again when it finishes")
                before = MANAGER.live_context_size()
                if action in {"stop", "replace"}:
                    if is_denied(row["model"]) or (row["backend"] not in {"ollama", "lmstudio"} and any(
                            is_denied(other["model"]) for other in self.rows if other["port"] == row["port"])):
                        raise ValueError("ANZU never stops this model")
                    if not row["can_stop"]:
                        raise ValueError("This server does not expose a safe stop operation")
                    native_unload = row["backend"] in {"ollama", "lmstudio"}
                    if native_unload:
                        await unload_native(row)
                    else:
                        await asyncio.to_thread(stop_listener, row)
                    self._forget_stopped(row)
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
                    IDLE_UNLOAD.explicit_load()  # the owner chose this model: an explicit Load
                    updated = settings.model_copy(deep=True)
                    if action == "use":
                        # A discovered llama.cpp is external too: never take ownership of its process.
                        updated.inference.backend = row["backend"] if row["backend"] != "llama.cpp" else "remote"
                        updated.inference.host = row.get("host", "127.0.0.1")
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
                from ..engine_mode import model_enabled
                if not model_enabled(settings):
                    await asyncio.sleep(10)
                    continue
                selected = next((r for r in self.rows if r["choice"] == "use"
                                 and r["port"] == settings.inference.port
                                 and r["model"] == settings.inference.remote_model
                                 and settings.inference.host in {"127.0.0.1", "localhost"}), None)
                if (settings.inference.auto_load and selected and not selected.get("busy") and not MANAGER.state.loaded
                        and not MANAGER.state.loading and not IDLE_UNLOAD.background_blocked()):
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
