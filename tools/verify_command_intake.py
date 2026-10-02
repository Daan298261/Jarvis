"""Read-only desktop proof of command intake; sample commands are never executed.

Run: python tools/verify_command_intake.py
Uses the installed, persisted Laya runtime. No fixtures or model downloads.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent import request_routing
from app.agent.planning import route_request
from app.decision.laya import runtime


async def main() -> None:
    runtime.restore_on_startup()
    deadline = time.monotonic() + 60
    while not runtime.is_ready() and time.monotonic() < deadline:
        status = runtime.status()
        if status.get("load_error") or not status.get("enabled"):
            break
        await asyncio.sleep(0.25)
    status = runtime.status()
    if not runtime.is_ready() or status.get("fixture"):
        print(json.dumps({"verified": False, "reason": "Real Laya is not ready",
                          "enabled": status.get("enabled"), "error": status.get("load_error")}, indent=2))
        raise SystemExit(1)
    original = request_routing.decide
    samples = []
    for prompt in ("hello", "open steam", "read C:/example.txt", "what is the weather tomorrow?"):
        for repeat in range(3):
            evidence = {}

            def observe(*args, _evidence=evidence, **kwargs):
                result = original(*args, **kwargs)
                _evidence.update(provider=result.provider, source=result.source,
                                 fallback=result.fallback_used, provider_ms=result.latency.total_ms)
                return result

            request_routing.decide = observe
            started = time.perf_counter()
            route = await request_routing.evaluate_request_route(prompt, route_request(prompt))
            samples.append({"prompt": prompt, "repeat": repeat, "route": route.kind,
                            "task_class": route.task_class,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), **evidence})
    request_routing.decide = original
    print(json.dumps({"fixture": False, "device": status.get("device"),
                      "version": status.get("version"), "samples": samples}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
