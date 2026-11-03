"""Release the models ANZU itself loaded, then prove it was released.

Used by the HUD "Unload model" button (every ANZU-loaded model) and by the idle-unload
timer (the models that went idle). The registry of ANZU-loaded models (``LoadedModels``)
filters every backend listing: a model ANZU did not load is never unloaded, so Black
Grid's ``bgm-ingest-9b`` in Ollama or LM Studio stays resident whatever the toggle says.
Covered: loopback Ollama (``keep_alive=0``), loopback LM Studio (its unload API; the CLI
per instance for older builds) and ANZU's llama-server workers (main model and front
responder). Each backend is re-read afterwards; a model still resident is a failure with a
reason, never a silent success.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import psutil

from ..config import AppSettings
from .backends import LMSTUDIO_ALIASES, OLLAMA_ALIASES, inference_headers, parse_models_payload
from .idle_unload import IDLE_UNLOAD
from .keep_alive import current_settings, idle_unload_seconds, keep_warm_enabled
from .loaded_models import FRONT, LLAMA_SERVER, LMSTUDIO, LOADED, OLLAMA, WORKER, Entry, canonical

log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
OLLAMA_DEFAULT_PORT = 11434
LMSTUDIO_DEFAULT_PORT = 1234
REQUEST_TIMEOUT_SECONDS = 15.0
VERIFY_ATTEMPTS = 6
VERIFY_DELAY_SECONDS = 0.5

ClientFactory = Callable[[str], httpx.AsyncClient]
CliRunner = Callable[[list[str]], subprocess.CompletedProcess]
_release_lock = asyncio.Lock()


def _client(api_key: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False, headers=inference_headers(api_key))


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def _endpoints(settings: AppSettings, aliases: set[str], default_port: int) -> list[tuple[str, int, str]]:
    """Loopback endpoints ANZU talks to for one backend family (never another computer)."""
    found: list[tuple[str, int, str]] = []
    inference = settings.inference
    if (inference.backend or "").strip().lower() in aliases and (inference.host or "").strip().lower() in LOOPBACK:
        found.append((inference.host.strip(), int(inference.port), inference.api_key or ""))
    if all(port != default_port for _, port, _ in found):
        found.append(("127.0.0.1", default_port, ""))
    return found


def _row(backend: str, endpoint: str) -> dict[str, Any]:
    return {"backend": backend, "endpoint": endpoint, "running": True, "released": [], "left_alone": [], "ok": True, "detail": ""}


def _not_running(row: dict[str, Any], selection: _Selection, backend: str) -> dict[str, Any]:
    row.update(running=False, detail="not running; nothing to unload")
    selection.mark_absent(backend, [])
    return row


async def _verified(read_loaded: Callable[[], Awaitable[list[str]]], released: list[str]) -> list[str]:
    """Names from ``released`` still resident after the attempts (empty means verified)."""
    wanted = {canonical(name) for name in released}
    still: list[str] = list(released)
    for attempt in range(VERIFY_ATTEMPTS):
        loaded = {canonical(name) for name in await read_loaded()}
        still = [name for name in released if canonical(name) in wanted & loaded]
        if not still:
            return []
        if attempt + 1 < VERIFY_ATTEMPTS:
            await asyncio.sleep(VERIFY_DELAY_SECONDS)
    return still


class _Selection:
    """The registry entries this release may touch, and which of them it actually processed."""

    def __init__(self, entries: list[Entry]) -> None:
        self.entries = {e.key: e for e in entries}
        self.done: dict[tuple[str, str], Entry] = {}
        self.failed: set[tuple[str, str]] = set()

    def pick(self, backend: str, ids: list[str]) -> Entry | None:
        wanted = {canonical(i) for i in ids if i}
        return next((e for e in self.entries.values() if e.backend == backend and e.ids() & wanted), None)

    def mark_absent(self, backend: str, present: list[str]) -> None:
        """Entries the backend no longer holds (its own expiry unloaded them) are stale: drop them."""
        here = {canonical(name) for name in present}
        for entry in self.entries.values():
            if entry.backend == backend and not entry.ids() & here:
                self.done.setdefault(entry.key, entry)


async def _release_ollama(host: str, port: int, key: str, factory: ClientFactory, selection: _Selection) -> dict[str, Any]:
    base = f"http://{host}:{port}"
    row = _row(OLLAMA, f"{host}:{port}")

    async with factory(key) as client:
        async def loaded() -> list[str]:
            response = await client.get(base + "/api/ps")
            response.raise_for_status()
            return parse_models_payload("/api/ps", response.json())

        try:
            names = await loaded()
        except httpx.ConnectError:
            return _not_running(row, selection, OLLAMA)
        except (httpx.HTTPError, ValueError) as exc:
            row.update(ok=False, detail=f"could not read /api/ps: {exc}"[:240])
            return row
        selection.mark_absent(OLLAMA, names)
        failures: list[str] = []
        entries: dict[str, Entry] = {}
        for name in names:
            entry = selection.pick(OLLAMA, [name])
            if entry is None:
                row["left_alone"].append(name)  # not loaded by ANZU: never touched
                continue
            try:
                response = await client.post(base + "/api/generate", json={"model": name, "keep_alive": 0})
                response.raise_for_status()
                row["released"].append(name)
                entries[name] = entry
            except httpx.HTTPError as exc:
                failures.append(f"{name}: {exc}")
                selection.failed.add(entry.key)
        try:
            still = await _verified(loaded, row["released"])
        except (httpx.HTTPError, ValueError) as exc:
            row.update(ok=False, detail=f"could not verify /api/ps after unload: {exc}"[:240])
            selection.failed.update(e.key for e in entries.values())
            return row
    for name, entry in entries.items():
        if name in still:
            selection.failed.add(entry.key)
        else:
            selection.done[entry.key] = entry
    if still:
        failures.append("still loaded after unload: " + ", ".join(still))
    if failures:
        row.update(ok=False, detail="; ".join(failures)[:400])
    return row


async def _release_lmstudio(host: str, port: int, key: str, factory: ClientFactory, cli_runner: CliRunner,
                            selection: _Selection) -> dict[str, Any]:
    base = f"http://{host}:{port}"
    row = _row(LMSTUDIO, f"{host}:{port}")

    async with factory(key) as client:
        async def native() -> list[tuple[str, str]] | None:
            """(model key, instance id) pairs from LM Studio's native API; ``None`` without inventory."""
            response = await client.get(base + "/api/v1/models")
            if not response.is_success:
                return None
            body = response.json()
            models = body.get("models") if isinstance(body, dict) else None
            if not isinstance(models, list) or not any(isinstance(m, dict) and "loaded_instances" in m for m in models):
                return None
            return [(str(m.get("key") or ""), str(i["id"])) for m in models if isinstance(m, dict)
                    for i in (m.get("loaded_instances") or []) if isinstance(i, dict) and i.get("id")]

        async def legacy() -> list[tuple[str, str]]:
            response = await client.get(base + "/api/v0/models")
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            return [(str(m["id"]), str(m["id"])) for m in (data or [])
                    if isinstance(m, dict) and m.get("state") == "loaded" and m.get("id")]

        try:
            pairs = await native()
            use_native = pairs is not None
            if pairs is None:
                pairs = await legacy()
        except httpx.ConnectError:
            return _not_running(row, selection, LMSTUDIO)
        except (httpx.HTTPError, ValueError) as exc:
            row.update(ok=False, detail=f"could not read the loaded models: {exc}"[:240])
            return row

        async def read_loaded() -> list[str]:
            return [instance for _key, instance in (await native() if use_native else await legacy()) or []]

        selection.mark_absent(LMSTUDIO, [x for pair in pairs for x in pair])
        failures: list[str] = []
        entries: dict[str, Entry] = {}
        for model_key, instance in pairs:
            entry = selection.pick(LMSTUDIO, [instance, model_key])
            if entry is None:
                row["left_alone"].append(instance)  # not loaded by ANZU: never touched
                continue
            try:
                if use_native:
                    response = await client.post(base + "/api/v1/models/unload", json={"instance_id": instance})
                    response.raise_for_status()
                else:
                    from .lmstudio_server import lmstudio_cli

                    cli = lmstudio_cli()
                    if not cli:
                        raise RuntimeError("LM Studio has this model loaded but its CLI is not available to unload it")
                    completed = await asyncio.to_thread(cli_runner, [cli, "unload", instance])
                    if completed.returncode != 0:
                        raise RuntimeError((completed.stderr or completed.stdout or "lms unload failed").strip())
                row["released"].append(instance)
                entries[instance] = entry
            except (httpx.HTTPError, RuntimeError) as exc:
                failures.append(f"{instance}: {exc}")
                selection.failed.add(entry.key)
        try:
            still = await _verified(read_loaded, row["released"])
        except (httpx.HTTPError, ValueError) as exc:
            row.update(ok=False, detail=f"could not verify the unload: {exc}"[:240])
            selection.failed.update(e.key for e in entries.values())
            return row
    for instance, entry in entries.items():
        if instance in still:
            selection.failed.add(entry.key)
        else:
            selection.done[entry.key] = entry
    if still:
        failures.append("still loaded after unload: " + ", ".join(still))
    if failures:
        row.update(ok=False, detail="; ".join(failures)[:400])
    return row


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


async def _release_workers(selection: _Selection) -> tuple[list[dict[str, Any]], bool]:
    """Stop ANZU's llama-server workers and detach the main model. Returns rows and whether the front stopped."""
    from .front_runtime import FRONT_RUNTIME
    from .manager import MANAGER

    rows: list[dict[str, Any]] = []
    worker = selection.pick(LLAMA_SERVER, [WORKER])
    # An Ollama / LM Studio model ANZU released above also detaches ANZU's provider.
    attached = [e for e in selection.done.values() if e.backend in {OLLAMA, LMSTUDIO}
                and MANAGER.state.backend == e.backend and e.ids() & {canonical(MANAGER.state.remote_model)}]
    if worker is not None and (MANAGER.state.loaded or MANAGER.provider is not None or MANAGER.backend is not None):
        pid = MANAGER.backend.pid if MANAGER.backend is not None else None
        row = _row("llama-server", f"{MANAGER.state.host}:{MANAGER.state.port}")
        row["released"].append(MANAGER.state.profile)
        await MANAGER.unload()
        if MANAGER.state.loaded or MANAGER.provider is not None:
            row.update(ok=False, detail="the worker still reports a loaded model")
        elif pid is not None and await asyncio.to_thread(_alive, pid):
            row.update(ok=False, detail=f"llama-server pid {pid} is still running")
        if row["ok"]:
            selection.done[worker.key] = worker
        else:
            selection.failed.add(worker.key)
        rows.append(row)
    elif worker is not None:
        selection.done[worker.key] = worker  # nothing was running; the registry entry was stale
    if attached and MANAGER.provider is not None:
        await MANAGER.unload()
    front_stopped = False
    front = selection.pick(LLAMA_SERVER, [FRONT])
    if front is not None and (FRONT_RUNTIME.running or FRONT_RUNTIME.decision.healthy):
        pid = FRONT_RUNTIME.pid
        row = _row("front responder", FRONT_RUNTIME.decision.endpoint or "local")
        row["released"].append(FRONT_RUNTIME.decision.model or "front")
        await FRONT_RUNTIME.stop()
        front_stopped = True
        if FRONT_RUNTIME.running:
            row.update(ok=False, detail="the front responder is still running")
        elif pid is not None and await asyncio.to_thread(_alive, pid):
            row.update(ok=False, detail=f"front llama-server pid {pid} is still running")
        if row["ok"]:
            selection.done[front.key] = front
        else:
            selection.failed.add(front.key)
        rows.append(row)
    elif front is not None:
        selection.done[front.key] = front
    return rows, front_stopped


def _refusal(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "refused": True, "reason": reason, "results": [], "keep_warm": keep_warm_enabled(), **extra}


def _nothing_reason(settings: AppSettings) -> str:
    if IDLE_UNLOAD.last_idle_released:
        minutes = max(1, idle_unload_seconds(settings) // 60)
        return (f"Nothing to unload: {', '.join(IDLE_UNLOAD.last_idle_released)} was unloaded after {minutes} "
                "minutes idle and loads again on your next request.")
    return "Nothing to unload: ANZU has no loaded model."


async def release_models(
    source: str = "manual",
    targets: list[tuple[str, str]] | None = None,
    *,
    settings: AppSettings | None = None,
    client_factory: ClientFactory | None = None,
    cli_runner: CliRunner | None = None,
) -> dict[str, Any]:
    """Unload ANZU-loaded models (all of them, or the ``targets`` registry keys) and verify.

    ``refused`` results (a request or load in flight, a task running, nothing to unload) carry a
    visible reason and leave every model and flag untouched.
    """
    from .front_runtime import FRONT_RUNTIME
    from .manager import MANAGER

    app = settings or current_settings()
    factory = client_factory or _client
    runner = cli_runner or _run_cli
    if _release_lock.locked():
        return _refusal("An unload is already running; wait for it to finish.")
    async with _release_lock:
        if MANAGER.state.loading:
            return _refusal("A model is still loading; try again when it has finished loading.")
        if FRONT_RUNTIME.starting:
            return _refusal("The front responder is starting; try again in a moment.")
        if source == "manual" and IDLE_UNLOAD.is_busy():
            return _refusal("ANZU is working on a task; try Unload when it finishes.")
        chosen = [e for e in LOADED.entries() if targets is None or e.key in set(targets)]
        selection = _Selection(chosen)
        if source == "manual" and not chosen:
            return _refusal(_nothing_reason(app), nothing_to_unload=True)
        async with MANAGER._request_lease.exclusive() as acquired:
            if not acquired:
                return _refusal("ANZU is answering a request; try again when it finishes.")
            results: list[dict[str, Any]] = []
            for host, port, key in _endpoints(app, OLLAMA_ALIASES, OLLAMA_DEFAULT_PORT):
                if any(e.backend == OLLAMA for e in chosen):
                    results.append(await _release_ollama(host, port, key, factory, selection))
            for host, port, key in _endpoints(app, LMSTUDIO_ALIASES, LMSTUDIO_DEFAULT_PORT):
                if any(e.backend == LMSTUDIO for e in chosen):
                    results.append(await _release_lmstudio(host, port, key, factory, runner, selection))
            workers, front_stopped = await _release_workers(selection)
            results.extend(workers)
    # Entries that were released (or were already gone) leave the registry; failures stay and wait a window.
    for key, entry in selection.done.items():
        if key not in selection.failed:
            LOADED.forget(entry)
    for key in selection.failed:
        if key in selection.entries:
            LOADED.defer(selection.entries[key])
    failed = [r for r in results if not r["ok"]]
    released = sum(len(r["released"]) for r in results)
    reason = "; ".join(f'{r["backend"]} {r["endpoint"]}: {r["detail"]}' for r in failed)
    if source == "manual" and not failed and not released:
        return _refusal(_nothing_reason(app), nothing_to_unload=True, results=results)
    if released:
        IDLE_UNLOAD.note_released(front=front_stopped)
        from .status_monitor import STATUS_MONITOR

        STATUS_MONITOR.invalidate()
    if source == "manual" and not failed:
        MANAGER.state.manually_unloaded = True  # stays unloaded until a user turn or an explicit Load
    payload = {"ok": not failed, "refused": False, "reason": reason, "source": source,
               "released_count": released, "results": results, "keep_warm": keep_warm_enabled(app)}
    log.info("Model release (%s): ok=%s released=%d %s", source, payload["ok"], released, reason)
    return payload
