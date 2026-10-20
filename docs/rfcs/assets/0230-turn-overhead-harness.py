"""RFC-0230 box evidence: code-path overhead of one desktop turn with mocked engines.

Front and worker providers answer instantly, so every millisecond measured here is
ANZU code (routing, reflex lane, DB commits, BUS, hold timers) -- not model time.
Run: PYTHONPATH=backend python turn_overhead.py  (from the repo root)
"""
from __future__ import annotations

import asyncio, json, os, statistics, sys, tempfile, time
from pathlib import Path

os.environ.setdefault("JARVIS_SKIP_MODEL", "1")
os.environ.setdefault("PYTEST_CURRENT_TEST", "rfc0230_harness")  # same isolation switches as the test suite

T0 = time.perf_counter()
from app.config import AppSettings  # noqa: E402
import app.config as config_mod  # noqa: E402
IMPORT_CONFIG_S = time.perf_counter() - T0


DETAIL = True

class FakeFront:
    model = "front-fake"

    def __init__(self, fail: bool = False):
        self.fail = fail

    async def chat_stream(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError("HTTP 500 from front template (simulated)")
        yield '{"front_action": "final_basic", "text": "RAM is temporary; storage is permanent."}'


class FakeWorker:
    model = "worker-fake"
    base_url = "http://127.0.0.1:9/v1"

    async def chat_stream(self, messages, **kwargs):
        for tok in ["RAM ", "holds ", "working ", "data. ", "Storage ", "keeps ", "files."]:
            yield tok


def pct(xs, p):
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1)))))
    return round(xs[k], 2)


async def main() -> dict:
    out: dict = {"host": "box (8 vCPU Xeon, shared; see loadavg)", "loadavg_start": open("/proc/loadavg").read().split()[:3]}
    tmp = Path(tempfile.mkdtemp(prefix="rfc0230-"))
    from app.db import session as session_mod
    await session_mod.configure_database(path=tmp / "jarvis.db")
    await session_mod.init_db()
    settings = AppSettings(allowed_directories=[str(tmp)], autonomy="autonomous", execution_mode="balanced", backup_enabled=False)
    settings.front_responder.enabled = True
    settings.front_responder.profile = "front_2b"
    settings.front_responder.timeout_ms = 1500
    settings.front_responder.speak_immediately = True
    import app.agent.loop as loop_mod
    loop_mod.load_settings = lambda: settings
    config_mod.load_settings = lambda: settings
    import app.agent.front_responder as fr
    fr.load_settings = lambda: settings
    from app.inference.manager import MANAGER
    from app.inference.front_runtime import FRONT_RUNTIME
    from app.tools.registry import REGISTRY
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384
    MANAGER.backend = None
    MANAGER.provider = FakeWorker()
    REGISTRY.apply_settings(settings)

    # --- reflex lane: decide_owner_turn wall time
    from app.agent.planning import route_request
    from app.decision.owner_turn import decide_owner_turn
    prompts = ["What is RAM?", "hi", "Say only the word ready", "Refactor the auth module and run the tests", "what's the weather tomorrow"]
    t = time.perf_counter(); await decide_owner_turn(prompts[0], baseline=route_request(prompts[0]), settings=settings, decision_tier="local"); first = (time.perf_counter() - t) * 1000
    xs, fallbacks = [], 0
    for i in range(300):
        p = prompts[i % len(prompts)]
        t = time.perf_counter()
        turn = await decide_owner_turn(p, baseline=route_request(p), settings=settings, decision_tier="local")
        xs.append((time.perf_counter() - t) * 1000)
    rr = []
    for i in range(300):
        p = prompts[i % len(prompts)]
        t = time.perf_counter(); route_request(p); rr.append((time.perf_counter() - t) * 1000)
    out["reflex_decide_owner_turn_ms"] = {"first_call": round(first, 2), "n": 300, "p50": pct(xs, 50), "p95": pct(xs, 95), "max": round(max(xs), 2)}
    out["route_request_ms"] = {"p50": pct(rr, 50), "p95": pct(rr, 95), "max": round(max(rr), 2)}

    # --- a full HUD typed turn: POST /api/tasks -> first chat_tts on the task channel
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI
    from app.api import tasks as tasks_api
    from app.events import BUS
    api = FastAPI(); api.include_router(tasks_api.router)

    async def one_turn(prompt: str, front: FakeFront) -> dict:
        FRONT_RUNTIME.reset_for_tests()
        FRONT_RUNTIME.mark_for_tests(distinct=True, provider=front)
        q = BUS.subscribe(None)
        marks: dict = {}
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as client:
            t0 = time.perf_counter()
            r = await client.post("/api/tasks", json={"prompt": prompt})
            marks["post_returned_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            assert r.status_code in (200, 201), r.text[:300]
            tid = r.json()["id"]
            deadline = t0 + 15
            while time.perf_counter() < deadline:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=max(0.01, deadline - time.perf_counter()))
                except asyncio.TimeoutError:
                    break
                if ev.get("task_id") not in (tid, "owner-chat", None) and not str(ev.get("task_id", "")).startswith("owner"):
                    continue
                key = f'{ev["kind"]}' + (":" + ev["title"] if ev["kind"] in ("stage", "chat_tts") else "")
                marks.setdefault(key + "_ms", round((time.perf_counter() - t0) * 1000, 1))
                if ev["kind"] in ("fastpath", "response_timing", "front_response_skipped") and DETAIL:
                    marks.setdefault(ev["kind"] + "_detail", (ev.get("detail") or "")[:400])
                if ev["kind"] in ("completed", "task_completed", "done", "final") or (ev["kind"] == "stage" and ev.get("title") in ("Completed", "Done")):
                    break
            # wait for runner
            runner = loop_mod.AGENT._tasks.get(tid)
            if runner:
                try:
                    await asyncio.wait_for(asyncio.shield(runner), timeout=10)
                except Exception:
                    pass
            marks["runner_done_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        BUS.unsubscribe(q, None)
        return marks

    for label, prompt in [("what_is_ram", "What is RAM?"), ("social_hi", "hey anzu, how are you?"), ("task", "Refactor the auth module and run the tests")]:
        out[f"hud_turn_{label}_front_ok"] = [await one_turn(prompt, FakeFront()) for _ in range(4)]
        out[f"hud_turn_{label}_front_http500"] = [await one_turn(prompt, FakeFront(fail=True)) for _ in range(2)]
    out["loadavg_end"] = open("/proc/loadavg").read().split()[:3]
    return out


if __name__ == "__main__":
    res = asyncio.run(main())
    print(json.dumps(res, indent=1))
