"""Opt-in RFC-0247 desktop smoke. Never unload any pre-existing model.

Run with the canonical Python: scripts/verify_model_manager.py --small-model qwen2.5:0.5b
The small model must already be downloaded. No core/server process is launched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx
import psutil
from fastapi import FastAPI

from app.api import model as api
from app.inference import ollama_runtime
from app.inference.model_launch import vram_snapshot
from app.inference.running_models import RunningModels, listener_inventory


async def verify(model: str) -> None:
    events = []
    def record(event, **fields):
        entry = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        events.append(entry)
        print(json.dumps(entry), flush=True)
        (ROOT / "LIVE_STARTSTOP.log").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    async with httpx.AsyncClient(timeout=10, trust_env=False) as native:
        async def loaded():
            response = await native.get("http://127.0.0.1:11434/api/ps")
            response.raise_for_status()
            return {r["name"] for r in response.json()["models"]}
        baseline = await loaded()
        if model in baseline:
            raise RuntimeError("The small model is already loaded by someone else; refusing to touch it")
        identities = await asyncio.to_thread(listener_inventory)
        protected = {port: identities[port] for port in (11434, 8746) if port in identities}
        record("baseline", loaded_models=sorted(baseline), protected_listeners=protected)
        with tempfile.TemporaryDirectory(prefix="anzu-0247-") as directory:
            runtime = RunningModels(Path(directory) / "choices.json")
            original = api.RUNNING_MODELS
            api.RUNNING_MODELS = runtime
            app = FastAPI()
            app.include_router(api.router)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-test") as client:
                async def call(path, body):
                    response = await client.post("/api/model/running" + path, json=body)
                    response.raise_for_status()
                    return response.json()
                attempted = False
                try:
                    discovery = await call("/scan", {})
                    telemetry = await asyncio.to_thread(vram_snapshot)
                    (ROOT / "LIVE_DISCOVERY.json").write_text(json.dumps({**discovery, "vram": telemetry}, indent=2), encoding="utf-8")
                    assert any(s["port"] == 11434 and s["backend"] == "ollama" for s in discovery["inventory"])
                    record("discovery", seconds_at=discovery["checked_at"], servers=[{"port": s["port"], "pid": s["pid"],
                        "kind": s["kind"], "loaded": s["models"], "available_count": len(s.get("available_models", []))} for s in discovery["inventory"]])
                    try:
                        await asyncio.to_thread(ollama_runtime._start_server, "127.0.0.1", 11434)
                    except ValueError as exc:
                        record("duplicate_serve_guard_refused_spawn", reason=str(exc))
                    else:
                        raise AssertionError("Duplicate server guard failed")
                    catalog = (await client.get("/api/model/running/profiles")).json()["profiles"]
                    profile = next(p for p in catalog if p["model"] == model and p["port"] == 11434)
                    body = {"profile_id": profile["id"], "context_size": 2048}
                    no_confirm = await client.post("/api/model/running/start", json=body)
                    assert no_confirm.status_code == 400
                    record("approval_gate", status=no_confirm.status_code)
                    preview = await call("/start/preview", body)
                    record("budget_preview", estimated_mib=preview["estimated_mib"], free_mib=preview["free_mib"],
                           requires_confirmation=preview["requires_confirmation"])
                    if preview["requires_confirmation"]:
                        raise RuntimeError("Smoke refuses unknown/over-budget starts to protect owner workloads")
                    # Recheck immediately before Start: never take over an owner's model.
                    if model in await loaded():
                        raise RuntimeError("Another client loaded the test model; refusing to touch it")
                    attempted = True
                    started = await call("/start", {**body, "confirm": True})
                    row = next(r for r in started["servers"] if r["model"] == model and r["port"] == 11434)
                    record("start_verified", model=model, context=row["metadata"][model].get("context_size"),
                           loaded_models=sorted(await loaded()))
                    stopped = await call(f"/{row['id']}/choice", {"action": "stop", "confirm": True})
                    assert model not in await loaded()
                    record("stop_verified", model=model, loaded_models=sorted(await loaded()))
                finally:
                    if attempted and model in await loaded():
                        # Only this script's previously absent small model can be cleaned up.
                        await runtime.scan(force=True)
                        row = next(r for r in runtime.rows if r["model"] == model and r["port"] == 11434)
                        await runtime.decide(row["id"], "stop")
                        record("cleanup_test_model", model=model)
                    api.RUNNING_MODELS = original
        final = await loaded()
        assert baseline <= final, "A baseline model disappeared; inspect owner activity before interpreting results"
        for port, identity in protected.items():
            process = psutil.Process(identity["pid"])
            assert process.create_time() == identity["created"]
            assert any(c.status == psutil.CONN_LISTEN and c.laddr.port == port for c in process.net_connections(kind="tcp"))
        record("owner_workloads_preserved", loaded_models=sorted(final), protected_pids=[p["pid"] for p in protected.values()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small-model", required=True, choices=["qwen2.5:0.5b", "qwen3.5:0.8b"])
    asyncio.run(verify(parser.parse_args().small_model))
