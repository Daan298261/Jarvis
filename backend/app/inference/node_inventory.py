"""Read-only inventory of the portal node's model servers and recognized AI apps."""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import time
from urllib.parse import urlparse

import psutil
import httpx

from ..config import load_settings
from .running_models import KNOWN_PORTS, probe

# Names identify programs, never models or active chat sessions. No cmdline/env reads.
PROGRAMS = {
    "codex": ("Codex", "AI app"), "cursor": ("Cursor", "AI app"),
    "claude": ("Claude", "AI app"), "chatgpt": ("ChatGPT", "AI app"),
    "windsurf": ("Windsurf", "AI app"), "jan": ("Jan", "AI app"),
    "gpt4all": ("GPT4All", "AI app"), "anythingllm": ("AnythingLLM", "AI app"),
    "lm studio": ("LM Studio", "AI app"), "lmstudio": ("LM Studio", "AI app"),
    "lm-studio": ("LM Studio", "AI app"), "lms": ("LM Studio", "Model server"),
    "ollama": ("Ollama", "Model server"), "llama-server": ("llama.cpp", "Model server"),
    "koboldcpp": ("KoboldCpp", "Model server"), "vllm": ("vLLM", "Model server"),
    "sglang": ("SGLang", "Model server"), "open-webui": ("Open WebUI", "AI app"),
}


def program_kind(name: str) -> tuple[str, str] | None:
    return PROGRAMS.get(name.casefold().removesuffix(".exe"))


def process_inventory() -> dict:
    processes, warnings = {}, []
    try:
        for process in psutil.process_iter(["pid", "ppid", "name", "create_time"]):
            try:
                info = process.info
                processes[int(info["pid"])] = info
            except (psutil.Error, OSError, KeyError, TypeError):
                warnings.append("Some processes were inaccessible.")
    except (psutil.Error, OSError):
        warnings.append("Process enumeration was unavailable.")
    apps, internal_workers = {}, set()
    for pid, info in processes.items():
        kind = program_kind(str(info.get("name") or ""))
        if kind is None:
            continue
        root, cursor, seen = pid, info.get("ppid"), {pid}
        while cursor in processes and cursor not in seen:
            seen.add(cursor)
            parent = processes[cursor]
            parent_kind = program_kind(str(parent.get("name") or ""))
            if kind[0] == "llama.cpp" and parent_kind and parent_kind[0] == "Ollama":
                kind = parent_kind
                internal_workers.add(pid)
            if parent_kind and parent_kind[0] == kind[0]:
                root = cursor
            cursor = parent.get("ppid")
        row = apps.setdefault((kind[0], root), {"id": f"{kind[0]}:{root}", "name": kind[0],
            "category": kind[1], "pid": root, "process_count": 0, "status": "Process observed"})
        row["process_count"] += 1
    listeners = {}
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if connection.status != psutil.CONN_LISTEN or not connection.pid or not connection.laddr:
                continue
            if connection.laddr.ip not in {"127.0.0.1", "0.0.0.0", "::", "::1"}:
                continue
            info = processes.get(connection.pid, {})
            kind = program_kind(str(info.get("name") or ""))
            if kind:
                address = "::1" if ":" in connection.laddr.ip else "127.0.0.1"
                if listeners.get(connection.laddr.port, {}).get("address") == "127.0.0.1":
                    continue
                listeners[connection.laddr.port] = {"pid": connection.pid, "name": kind[0],
                    "process_name": info.get("name"), "created": info.get("create_time"), "address": address,
                    "internal_worker": connection.pid in internal_workers}
    except (psutil.Error, OSError):
        warnings.append("Listener enumeration was unavailable; only known/configured ports were checked.")
    return {"programs": sorted(apps.values(), key=lambda item: (item["name"], item["pid"])),
            "listeners": listeners, "warnings": sorted(set(warnings))}


def node_identity() -> dict:
    from ..swarm.nodes import identity_path
    try:
        identity = json.loads(identity_path().read_text(encoding="utf-8"))
        node_id = identity.get("node_id") if isinstance(identity, dict) else None
    except (OSError, ValueError, TypeError):
        node_id = None
    return {"id": node_id, "hostname": socket.gethostname(), "scope": "portal_node"}


class NodeInventory:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._snapshot: dict | None = None

    async def scan(self, *, force: bool = False) -> dict:
        async with self._lock:
            if not force and self._snapshot and time.time() - self._snapshot["checked_at"] < 10:
                return self._snapshot
            from .manager import MANAGER
            from .front_runtime import FRONT_RUNTIME
            settings = await asyncio.to_thread(load_settings)
            system, node = await asyncio.gather(asyncio.to_thread(process_inventory), asyncio.to_thread(node_identity))
            listeners = system["listeners"]
            configured = {int(settings.front_responder.port), int(MANAGER.state.port or settings.inference.port)}
            if settings.inference.host in {"localhost", "127.0.0.1", "::1"}:
                configured.add(int(settings.inference.port))
            secondary = (set(KNOWN_PORTS) | set(listeners)) - configured
            # Ollama's private llama.cpp port exposes the same resident weights,
            # not an additional model instance. Its /api/ps is authoritative.
            all_ports = sorted(configured) + sorted(port for port in secondary if not listeners.get(port, {}).get("internal_worker"))
            ports = [port for port in all_ports if 0 < port <= 65535][:40]
            warnings = list(system["warnings"])
            if len(all_ports) > 40:
                warnings.append("The 40-port scan limit was reached; detection is incomplete.")
            async def inspect(port, shared_client):
                key = settings.inference.api_key if port == settings.inference.port and settings.inference.host in {"localhost", "127.0.0.1", "::1"} else ""
                try:
                    if listeners.get(port, {}).get("address") == "::1":
                        return await probe(port, api_key=key, host="::1", include_embeddings=True, client=None if key else shared_client)
                    return await probe(port, api_key=key, include_embeddings=True, client=None if key else shared_client)
                except Exception:
                    warnings.append(f"Port {port} could not be inspected.")
                    return None
            # HTTP client setup, JSON parsing and native probes must not block the portal loop.
            async def inspect_all():
                # One client avoids serial TLS-context initialization starving
                # the network deadlines of concurrently inspected ports.
                async with httpx.AsyncClient(timeout=1.0, trust_env=False, follow_redirects=False) as client:
                    return await asyncio.gather(*(inspect(port, client) for port in ports))
            results = await asyncio.to_thread(lambda: asyncio.run(inspect_all()))
            models, servers = [], []
            front_model = FRONT_RUNTIME.model_id(settings)
            front_endpoint = urlparse(getattr(FRONT_RUNTIME._decision, "endpoint", "") or "")
            for port, result in zip(ports, results):
                process = listeners.get(port)
                if not result:
                    if process:
                        servers.append({"port": port, "program": process["name"], "pid": process["pid"],
                                        "verified_loaded": False, "models": [], "status": "Model API unavailable or no resident model reported"})
                    continue
                owned = bool(MANAGER.state.manages_process and MANAGER.state.loaded and process
                             and MANAGER.state.pid == process["pid"])
                front_owned = bool(FRONT_RUNTIME._decision.healthy and FRONT_RUNTIME._backend and process
                                   and getattr(FRONT_RUNTIME._backend, "pid", None) == process["pid"])
                verified = bool(result.get("verified_loaded") or owned or front_owned)
                source = result.get("source") or "openai_advertised"
                if owned or front_owned:
                    source = "anzu_managed_ready"
                servers.append({"port": port, "program": (process or {}).get("name") or result["backend"],
                    "pid": (process or {}).get("pid"), "verified_loaded": verified,
                    "models": result["models"], "status": "Loaded inventory verified" if verified else "Advertised models; loading unverified"})
                for name in result["models"]:
                    metadata = (result.get("metadata") or {}).get(name, {})
                    selected_names = {getattr(MANAGER.provider, "model", "") or MANAGER.state.remote_model}
                    model_key = metadata.get("model_key")
                    unique_key = bool(model_key and sum(1 for value in (result.get("metadata") or {}).values() if value.get("model_key") == model_key) == 1)
                    exact_selected = any(item in selected_names for item in result["models"])
                    active = bool(MANAGER.state.loaded and settings.inference.host in {"127.0.0.1", "localhost", "::1"}
                                  and port == MANAGER.state.port and (name in selected_names or (not exact_selected and unique_key and model_key in selected_names)))
                    front_local = front_endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and (front_endpoint.port or 80) == port
                    roles = (["Worker"] if active or owned else []) + (["Front"] if front_owned or (front_local and name == front_model) else [])
                    models.append({"id": hashlib.sha256(f"{port}:{name}".encode()).hexdigest()[:24],
                        "model": name, "display_name": metadata.get("display_name") or name,
                        "model_key": metadata.get("model_key"), "backend": result["backend"],
                        "port": port, "pid": (process or {}).get("pid"), "roles": roles,
                        "verified_loaded": verified, "source": source, "active": active,
                        "busy": result.get("busy"), "parameters": metadata.get("parameters"),
                        "quantization": metadata.get("quantization"), "context_size": metadata.get("context_size"),
                        "size_bytes": metadata.get("size_bytes")})
            self._snapshot = {"node": node, "models": models, "servers": servers, "programs": system["programs"],
                "warnings": sorted(set(warnings)), "checked_at": time.time(), "read_only": True,
                "coverage": "Recognized local AI programs and exposed model APIs. Browser-only sessions and inaccessible processes may not appear."}
            return self._snapshot


NODE_INVENTORY = NodeInventory()
