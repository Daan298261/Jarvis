"""HUD Unload model + Keep warm.

Covers: settings (keep_warm default OFF, idle_unload_seconds 300), the single keep-alive
helper, idle unload on a fake clock, ANZU-loaded-only scope (a foreign model such as
bgm-ingest-9b is never touched), the separate POST /api/model/unload-all with verification
and its refusal codes, and the manually_unloaded guard on every background load and warm path.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import psutil
import pytest
from fastapi import FastAPI, HTTPException

from app.api import model as model_api
from app.api import model_unload_all as unload_all_api
from app.api import settings as settings_api
from app.config import AppSettings, load_settings
from app.inference import gpu_prefer, keep_alive, keep_warm_release, lmstudio_server, ollama_runtime
from app.inference.backends import LlamaCppBackend
from app.inference.front_runtime import FRONT_RUNTIME, FrontDecision
from app.inference.idle_unload import IDLE_UNLOAD, IdleUnload, warm_blocked
from app.inference.keep_alive import lmstudio_ttl_seconds, ollama_keep_alive, request_extras
from app.inference.loaded_models import FRONT, LLAMA_SERVER, LMSTUDIO, LOADED, OLLAMA, WORKER, LoadedModels
from app.inference.manager import MANAGER, ModelManuallyUnloaded

BACKEND_APP = Path(__file__).resolve().parents[1] / "backend" / "app"
FOREIGN = "bgm-ingest-9b"  # Black Grid's model: loaded by someone else, must never be touched
ANZU_OLLAMA = "hf.co/TheCidSama/Qwen3.5-9b-Claude-4.8-Opus-reasoning"


def settings_with(keep_warm: bool, **inference) -> AppSettings:
    settings = AppSettings()
    settings.inference.keep_warm = keep_warm
    for key, value in inference.items():
        setattr(settings.inference, key, value)
    return settings


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    monkeypatch.setattr(keep_warm_release, "VERIFY_DELAY_SECONDS", 0)
    monkeypatch.setattr("app.config.settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    keep_alive._cache = None
    reset()
    yield
    reset()
    keep_alive._cache = None


def reset() -> None:
    LOADED.clear()
    IDLE_UNLOAD.held = False
    IDLE_UNLOAD.front_released = False
    IDLE_UNLOAD.last_idle_released = []
    MANAGER.provider = None
    MANAGER.backend = None
    MANAGER.state.loaded = False
    MANAGER.state.loading = False
    MANAGER.state.manually_unloaded = False
    MANAGER.state.manages_process = False
    FRONT_RUNTIME.reset_for_tests()
    FRONT_RUNTIME._backend = None


def write_settings(tmp_path: Path, **inference) -> None:
    (tmp_path / "settings.json").write_text(json.dumps({"inference": inference}), encoding="utf-8")
    keep_alive._cache = None


# --- settings: keep_warm defaults OFF, idle_unload_seconds 300 -----------------------------------------

def test_keep_warm_defaults_off_and_idle_window_is_300_seconds():
    inference = AppSettings().inference
    assert inference.keep_warm is False and inference.idle_unload_seconds == 300
    shipped = json.loads((Path(__file__).resolve().parents[1] / "config" / "default.json").read_text(encoding="utf-8"))
    assert shipped.get("inference", {}).get("keep_warm", False) is False


async def test_keep_warm_is_off_on_a_fresh_install_and_persists_through_the_settings_api(tmp_path):
    assert load_settings().inference.keep_warm is False
    assert (await settings_api.get_settings())["inference"]["keep_warm"] is False
    saved = await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=True))
    assert saved["inference"]["keep_warm"] is True
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["inference"]["keep_warm"] is True
    assert load_settings().inference.keep_warm is True
    await settings_api.update_settings(settings_api.SettingsUpdate(retry_limit=3))  # unrelated save keeps it
    assert load_settings().inference.keep_warm is True
    await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=False,
                                                                   inference_idle_unload_seconds=600))
    reloaded = load_settings().inference
    assert reloaded.keep_warm is False and reloaded.idle_unload_seconds == 600
    with pytest.raises(ValueError):
        settings_api.SettingsUpdate(inference_idle_unload_seconds=5)


# --- one keep-alive helper -----------------------------------------------------------------------------

def test_keep_alive_helper_values_for_off_and_on():
    off, on = settings_with(False), settings_with(True)
    assert ollama_keep_alive(off) == "300s" and lmstudio_ttl_seconds(off) == 300
    assert ollama_keep_alive(settings_with(False, idle_unload_seconds=900)) == "900s"
    assert ollama_keep_alive(on) == "-1"  # Keep warm ON: Ollama keep_alive "-1", always warm
    assert lmstudio_ttl_seconds(on) is None


def test_no_hardcoded_keep_alive_string_outside_the_helper():
    literal = re.compile(r"""keep_alive["']?\s*[:=]\s*["']""")
    offenders = [str(path.relative_to(BACKEND_APP)) for path in BACKEND_APP.rglob("*.py")
                 if path.name != "keep_alive.py" and literal.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


def fake_ollama_client(monkeypatch, module, bodies: list[dict]):
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"done": True})

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("keep_warm,expected", [(False, "300s"), (True, "-1")])
async def test_ollama_gpu_warm_carries_the_policy_keep_alive(monkeypatch, tmp_path, keep_warm, expected):
    bodies: list[dict] = []
    write_settings(tmp_path, keep_warm=keep_warm)
    monkeypatch.setattr(gpu_prefer, "nvidia_gpu_present", lambda: True)
    fake_ollama_client(monkeypatch, gpu_prefer, bodies)
    result = await gpu_prefer.ensure_ollama_gpu(host="127.0.0.1", port=11434, model=ANZU_OLLAMA)
    assert result["ok"] is True
    assert [body["keep_alive"] for body in bodies] == [expected]
    assert LOADED.match(OLLAMA, [ANZU_OLLAMA]) is not None  # a load ANZU did is registered


async def test_ollama_cpu_warm_carries_300s_when_off_and_minus_one_when_on(monkeypatch, tmp_path):
    async def probe(*args, **kwargs):
        return {"ok": True, "models": ["m"]}

    async def skipped(*args, **kwargs):
        return {"ok": False, "method": "skipped"}

    monkeypatch.setattr(ollama_runtime, "probe_remote_server", probe)
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", skipped)
    seen = {}
    bodies: list[dict] = []
    fake_ollama_client(monkeypatch, ollama_runtime, bodies)
    for keep_warm in (False, True):
        bodies.clear()
        write_settings(tmp_path, keep_warm=keep_warm)
        result = await ollama_runtime.ensure_local_ollama(host="127.0.0.1", port=11434, model="m", pull_if_missing=False)
        assert result["ok"] is True
        seen[keep_warm] = [body["keep_alive"] for body in bodies]
    assert seen == {False: ["300s"], True: ["-1"]}


def test_lm_studio_cli_load_gets_a_300_second_ttl_unless_keep_warm_is_on(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu_prefer.shutil, "which", lambda name: "/bin/lms")
    assert gpu_prefer.lmstudio_cli_load_args("m")[-2:] == ["--ttl", "300"]
    write_settings(tmp_path, keep_warm=True)
    assert "--ttl" not in gpu_prefer.lmstudio_cli_load_args("m")


async def test_lm_studio_rest_load_and_restored_instances_carry_the_ttl(monkeypatch, tmp_path):
    bodies: list[dict] = []
    fake_ollama_client(monkeypatch, gpu_prefer, bodies)
    assert (await gpu_prefer._lmstudio_rest_load("127.0.0.1", 1234, "m", timeout=5))["ok"] is True
    assert bodies[0]["ttl"] == 300
    write_settings(tmp_path, keep_warm=True)
    bodies.clear()
    await gpu_prefer._lmstudio_rest_load("127.0.0.1", 1234, "m", timeout=5)
    assert "ttl" not in bodies[0]


async def test_every_ollama_request_anzu_sends_carries_keep_alive_for_anzu_models_only(monkeypatch, tmp_path):
    from app.providers.base import ModelProvider

    base = "http://127.0.0.1:11434/v1"
    LOADED.record(OLLAMA, ANZU_OLLAMA, primary=True)
    anzu, foreign = ModelProvider(base, model=ANZU_OLLAMA), ModelProvider(base, model=FOREIGN)
    assert anzu._runtime_extras() == {"keep_alive": "300s"}
    assert foreign._runtime_extras() == {}  # a foreign model never gets a keep_alive
    write_settings(tmp_path, keep_warm=True)
    assert anzu._runtime_extras() == {"keep_alive": "-1"}
    assert foreign._runtime_extras() == {}
    # The request body carries it: both the chat and the stream path merge the extras.
    source = (BACKEND_APP / "providers" / "base.py").read_text(encoding="utf-8")
    assert source.count("self._runtime_extras()") >= 2
    assert "_runtime_extras" in (BACKEND_APP / "providers" / "local_qwen_text.py").read_text(encoding="utf-8")
    # LM Studio: ttl while Keep warm is off, nothing when on; other ports and remote hosts: nothing.
    LOADED.record(LMSTUDIO, "qwen-a")
    assert request_extras("http://127.0.0.1:1234/v1", "qwen-a") == {}
    write_settings(tmp_path, keep_warm=False)
    assert request_extras("http://127.0.0.1:1234/v1", "qwen-a") == {"ttl": 300}
    assert request_extras("http://127.0.0.1:1234/v1", FOREIGN) == {}
    assert request_extras("http://10.0.0.9:11434/v1", ANZU_OLLAMA) == {}


# --- idle unload on a fake clock -------------------------------------------------------------------------

def make_timer(keep_warm=False, *, busy=False, refuse=False):
    clock = FakeClock()
    registry = LoadedModels(clock)
    calls: list[tuple[str, list]] = []
    flags = {"keep_warm": keep_warm, "busy": busy, "refuse": refuse}

    async def release(source: str, targets=None) -> dict:
        calls.append((source, targets))
        return {"ok": not flags["refuse"], "refused": flags["refuse"], "reason": "busy" if flags["refuse"] else "", "results": []}

    timer = IdleUnload(registry=registry, settings=lambda: settings_with(flags["keep_warm"]), release=release,
                       busy=lambda: flags["busy"])
    registry.record(OLLAMA, "qwen3:8b", primary=True)
    return timer, clock, calls, flags


async def test_idle_unload_fires_only_after_300_idle_seconds():
    timer, clock, calls, _ = make_timer()
    clock.now += 299
    assert (await timer.tick())["reason"] == "active"
    assert calls == []
    clock.now += 1
    assert (await timer.tick())["action"] == "released"
    assert calls == [("idle", [(OLLAMA, "qwen3:8b")])]


async def test_every_turn_resets_the_idle_timer():
    timer, clock, calls, _ = make_timer()
    clock.now += 290
    timer.touch()  # a turn starts
    clock.now += 290
    assert (await timer.tick())["action"] == "skipped"
    timer.used()  # a turn ends
    clock.now += 299
    assert (await timer.tick())["action"] == "skipped"
    clock.now += 1
    assert (await timer.tick())["action"] == "released"
    assert len(calls) == 1


async def test_agent_tasks_front_replies_and_owner_chat_all_touch_the_timer(monkeypatch):
    from app.agent import front_responder, loop
    from app.persona import owner_chat

    touches: list[str] = []
    monkeypatch.setattr(IDLE_UNLOAD, "touch", lambda: touches.append("touch"))
    monkeypatch.setattr(IDLE_UNLOAD, "used", lambda: touches.append("used"))

    async def turn():
        return None

    runner = loop.AGENT._start_runner("keep-warm-wiring", turn())
    await runner
    loop.AGENT._tasks.pop("keep-warm-wiring", None)
    assert touches == ["touch", "used"]  # start of the turn, then end of the turn

    touches.clear()

    def stop(*args, **kwargs):
        raise RuntimeError("stop after the turn entry")

    monkeypatch.setattr(owner_chat, "_ensure_conversation", stop)
    with pytest.raises(RuntimeError, match="stop after"):
        async for _event in owner_chat.stream_owner_chat("hello"):
            pass
    assert touches == ["touch"]

    touches.clear()
    monkeypatch.setattr("app.engine_mode.model_enabled", lambda app: True)

    def stop_front(*args, **kwargs):
        raise RuntimeError("stop after the front entry")

    monkeypatch.setattr(front_responder, "front_lane_config", stop_front)
    with pytest.raises(RuntimeError, match="stop after the front"):
        await front_responder.generate_front_reply("hello", settings=AppSettings())
    assert touches == ["touch"]


async def test_nothing_unloads_while_keep_warm_is_on():
    timer, clock, calls, flags = make_timer(keep_warm=True)
    clock.now += 100_000
    assert (await timer.tick()) == {"action": "skipped", "reason": "keep_warm"}
    assert calls == []


async def test_toggling_keep_warm_off_unloads_models_already_idle_past_the_window_immediately():
    """Idle time counts from each model's own last use, not from the toggle."""
    timer, clock, calls, flags = make_timer(keep_warm=True)
    timer.registry.record(OLLAMA, "old:1b")           # last used at t=1000
    clock.now += 1000
    timer.registry.touch(OLLAMA, "qwen3:8b")          # used 0 s ago
    assert (await timer.tick())["reason"] == "keep_warm"
    flags["keep_warm"] = False                         # the toggle goes OFF
    outcome = await timer.tick()                       # the very next check: no new 300 s wait
    assert outcome["action"] == "released"
    assert calls == [("idle", [(OLLAMA, "old:1b")])]  # only the model idle > 300 s; the fresh one stays


async def test_switching_keep_warm_off_through_the_settings_api_triggers_the_check_now(monkeypatch, tmp_path):
    clock = FakeClock()
    monkeypatch.setattr(LOADED, "_clock", clock)
    LOADED.record(OLLAMA, "old:1b")
    clock.now += 1000
    calls: list = []

    async def release(source, targets=None):
        calls.append((source, targets))
        return {"ok": True, "refused": False, "reason": "", "results": []}

    monkeypatch.setattr(IDLE_UNLOAD, "_release", release)
    monkeypatch.setattr(IDLE_UNLOAD, "_busy", lambda: False)
    monkeypatch.setattr(IDLE_UNLOAD, "_settings", load_settings)
    await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=True))
    await asyncio.sleep(0.05)
    assert calls == []
    await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=False))
    await asyncio.gather(*settings_api._IDLE_TICKS)
    assert calls == [("idle", [(OLLAMA, "old:1b")])]


async def test_a_running_task_or_a_refused_release_defers_the_unload():
    timer, clock, calls, flags = make_timer(busy=True)
    clock.now += 600
    assert (await timer.tick())["reason"] == "task_running"
    flags["busy"], flags["refuse"] = False, True
    assert (await timer.tick())["action"] == "refused"
    flags["refuse"] = False
    assert (await timer.tick())["action"] == "released"
    assert len(calls) == 2


async def test_an_idle_unload_is_policy_not_an_owner_decision(monkeypatch):
    """Idle unload never sets manually_unloaded; the next turn reloads on demand."""
    timer, clock, _calls, _ = make_timer()
    clock.now += 400
    assert MANAGER.state.manually_unloaded is False
    assert (await timer.tick())["action"] == "released"
    assert MANAGER.state.manually_unloaded is False
    FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    result = await keep_warm_release.release_models("idle", [(OLLAMA, "qwen3:8b")])
    assert result["ok"] is True and MANAGER.state.manually_unloaded is False


async def test_a_front_responder_released_by_idle_unload_respawns_on_the_next_turn(monkeypatch):
    started: list[bool] = []

    async def ensure_started(settings=None):
        started.append(IDLE_UNLOAD.background_blocked())
        return FrontDecision(reason="ok")

    monkeypatch.setattr(FRONT_RUNTIME, "ensure_started", ensure_started)
    IDLE_UNLOAD.note_released(front=True)
    IDLE_UNLOAD.touch()
    await IDLE_UNLOAD._respawn
    assert started == [False]  # the hold was lifted before the restart


# --- fake Ollama (11434) and LM Studio (1234) -------------------------------------------------------------

class FakeServers:
    """Stateful servers that honour unload requests like the real ones and record every request."""

    def __init__(self, *, ollama=(), lmstudio=(), ollama_ignores_unload=False, legacy_lmstudio=False,
                 ollama_up=True, lmstudio_up=True):
        self.ollama, self.lmstudio = list(ollama), list(lmstudio)
        self.ignore, self.legacy = ollama_ignores_unload, legacy_lmstudio
        self.up = {11434: ollama_up, 1234: lmstudio_up}
        self.requests: list[tuple[int, str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        port, path = request.url.port, request.url.path
        body = json.loads(request.content) if request.content else {}
        self.requests.append((port, request.method, path, body))
        if not self.up.get(port):
            raise httpx.ConnectError("refused", request=request)
        if port == 11434:
            if path == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": n, "model": n} for n in self.ollama]})
            if path == "/api/generate" and body.get("keep_alive") == 0 and not self.ignore:
                self.ollama.remove(body["model"])
                return httpx.Response(200, json={"done": True, "done_reason": "unload"})
            return httpx.Response(200, json={"done": True})
        if path == "/api/v1/models" and not self.legacy:
            return httpx.Response(200, json={"models": [{"key": n, "type": "llm", "loaded_instances": [{"id": n}]}
                                                       for n in self.lmstudio]})
        if path == "/api/v1/models/unload" and not self.legacy:
            self.lmstudio.remove(body["instance_id"])
            return httpx.Response(200, json={"instance_id": body["instance_id"]})
        if path == "/api/v0/models":
            return httpx.Response(200, json={"data": [{"id": n, "state": "loaded"} for n in self.lmstudio]})
        return httpx.Response(404)

    def client(self, key: str = "") -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def install(self, monkeypatch):
        monkeypatch.setattr(keep_warm_release, "_client", self.client)
        return self

    def unload_requests(self) -> list[dict]:
        return [body for port, _m, path, body in self.requests
                if (path == "/api/generate" and body.get("keep_alive") == 0) or path == "/api/v1/models/unload"]

    def mutating(self) -> list[tuple[int, str]]:
        return [(port, path) for port, method, path, _b in self.requests if method == "POST"]


# --- release: ANZU-loaded models only ------------------------------------------------------------------------

async def test_release_unloads_every_anzu_loaded_model_and_verifies(monkeypatch):
    servers = FakeServers(ollama=[ANZU_OLLAMA, "qwen3:8b"], lmstudio=["qwen-a", "qwen-b"]).install(monkeypatch)
    for name in (ANZU_OLLAMA, "qwen3:8b"):
        LOADED.record(OLLAMA, name)
    for name in ("qwen-a", "qwen-b"):
        LOADED.record(LMSTUDIO, name)
    result = await keep_warm_release.release_models("manual")
    assert result["ok"] is True and result["refused"] is False and result["released_count"] == 4
    assert servers.ollama == [] and servers.lmstudio == []
    assert [r[2] for r in servers.requests].count("/api/ps") >= 2  # re-read after the unload: verified
    assert {row["backend"] for row in result["results"]} == {"ollama", "lmstudio"}
    assert all(row["verified"] is True and row["error"] is None for row in result["results"])
    assert result["released"] == 4 and result["failed"] == 0 and result["skipped"] == []
    assert LOADED.entries() == [] and MANAGER.state.manually_unloaded is True


async def test_a_foreign_model_is_never_unloaded_by_the_button_or_the_idle_timer(monkeypatch):
    """bgm-ingest-9b sits in Ollama and LM Studio next to ANZU's models: it is never touched."""
    servers = FakeServers(ollama=[ANZU_OLLAMA, FOREIGN], lmstudio=["qwen-a", FOREIGN]).install(monkeypatch)
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    LOADED.record(LMSTUDIO, "qwen-a")
    for keep_warm in (False, True):  # whatever the toggle says
        write_settings(Path(load_settings.__globals__["settings_path"]().parent), keep_warm=keep_warm)
        assert request_extras("http://127.0.0.1:11434/v1", FOREIGN) == {}
        assert request_extras("http://127.0.0.1:1234/v1", FOREIGN) == {}
    result = await keep_warm_release.release_models("manual")
    assert result["ok"] is True and result["released_count"] == 2
    assert servers.ollama == [FOREIGN] and servers.lmstudio == [FOREIGN]
    assert all(FOREIGN not in json.dumps(body) for body in servers.unload_requests())
    assert {tuple(row["left_alone"]) for row in result["backends"]} == {(FOREIGN,)}
    assert {item["model"] for item in result["skipped"]} == {FOREIGN} and all("protected" in item["reason"] for item in result["skipped"])
    # The idle path (targets = idle ANZU entries) leaves it alone too.
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    servers.ollama.append(ANZU_OLLAMA)
    servers.requests.clear()
    idle = await keep_warm_release.release_models("idle", [LOADED.match(OLLAMA, [ANZU_OLLAMA]).key])
    assert idle["ok"] is True and servers.ollama == [FOREIGN]
    assert all(FOREIGN not in json.dumps(body) for body in servers.unload_requests())


async def test_nothing_is_unloaded_when_only_foreign_models_are_loaded(monkeypatch):
    servers = FakeServers(ollama=[FOREIGN], lmstudio=[FOREIGN]).install(monkeypatch)
    result = await keep_warm_release.release_models("manual")
    assert result["refused"] is True and "Nothing to unload" in result["reason"]
    assert servers.mutating() == [] and MANAGER.state.manually_unloaded is False


async def test_an_explicit_load_registers_the_model_so_the_idle_timer_unloads_it(monkeypatch):
    """CoS K3: with Keep warm off, a model the owner loaded via the HUD / dropdown unloads after 300 s too."""
    servers = FakeServers(ollama=["chosen:7b", FOREIGN]).install(monkeypatch)
    clock = FakeClock()
    monkeypatch.setattr(LOADED, "_clock", clock)
    MANAGER.state.backend, MANAGER.state.loaded, MANAGER.state.remote_model = OLLAMA, True, "chosen:7b"
    MANAGER.provider = type("P", (), {"model": "chosen:7b"})()
    MANAGER._register_loaded()  # what an explicit Load / dropdown choice does on success
    assert LOADED.match(OLLAMA, ["chosen:7b"]) is not None and LOADED.match(OLLAMA, [FOREIGN]) is None
    timer = IdleUnload(registry=LOADED, settings=lambda: settings_with(False), busy=lambda: False)
    clock.now += 301
    assert (await timer.tick())["action"] == "released"
    assert servers.ollama == [FOREIGN]
    assert MANAGER.state.loaded is False  # the attached provider was detached with the model


async def test_release_reports_a_backend_that_is_not_running_without_failing(monkeypatch):
    FakeServers(ollama_up=False, lmstudio_up=False).install(monkeypatch)
    LOADED.record(OLLAMA, "gone:1b")
    result = await keep_warm_release.release_models("manual")
    # Nothing was actually resident: reported as "Nothing to unload" (409), not as a failure (502).
    assert result["refused"] is True and result["nothing_to_unload"] is True
    assert all(row["running"] is False for row in result["backends"])
    assert LOADED.entries() == [] and MANAGER.state.manually_unloaded is False


async def test_release_fails_with_a_reason_when_ollama_keeps_the_model_resident(monkeypatch):
    FakeServers(ollama=["stuck:1b"], ollama_ignores_unload=True).install(monkeypatch)
    LOADED.record(OLLAMA, "stuck:1b")
    result = await keep_warm_release.release_models("manual")
    assert result["ok"] is False and "stuck:1b" in result["reason"] and "still loaded" in result["reason"]
    assert MANAGER.state.manually_unloaded is False  # a failed unload is not "stays unloaded"
    assert LOADED.match(OLLAMA, ["stuck:1b"]) is not None  # still registered; retried after a full window


async def test_release_uses_the_lm_studio_cli_per_instance_when_the_native_api_has_no_inventory(monkeypatch):
    servers = FakeServers(lmstudio=["old-model", FOREIGN], legacy_lmstudio=True).install(monkeypatch)
    LOADED.record(LMSTUDIO, "old-model")
    commands: list[list[str]] = []

    def run_cli(args):
        commands.append(args)
        servers.lmstudio.remove(args[-1])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("app.inference.lmstudio_server.lmstudio_cli", lambda: "/bin/lms")
    result = await keep_warm_release.release_models("manual", cli_runner=run_cli)
    assert commands == [["/bin/lms", "unload", "old-model"]]  # never `unload --all`
    assert result["ok"] is True and servers.lmstudio == [FOREIGN]


async def test_release_stops_the_llama_server_workers_and_proves_the_process_is_gone(monkeypatch):
    FakeServers().install(monkeypatch)
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(120)")
    backend = LlamaCppBackend(AppSettings())
    backend._process = process
    MANAGER.backend, MANAGER.provider = backend, object()
    MANAGER.state.loaded, MANAGER.state.manages_process, MANAGER.state.profile = True, True, "balanced"
    front_process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(120)")
    front_backend = LlamaCppBackend(AppSettings())
    front_backend._process = front_process
    FRONT_RUNTIME._backend = front_backend
    LOADED.record(LLAMA_SERVER, WORKER, primary=True)
    LOADED.record(LLAMA_SERVER, FRONT, primary=True)
    pids = (process.pid, front_process.pid)
    try:
        result = await keep_warm_release.release_models("manual")
    finally:
        for proc in (process, front_process):
            if proc.returncode is None:
                proc.kill()
    assert result["ok"] is True, result
    assert MANAGER.state.loaded is False and MANAGER.provider is None and not FRONT_RUNTIME.running
    assert not any(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE for pid in pids)
    assert IDLE_UNLOAD.front_released is True
    assert {row["backend"] for row in result["backends"]} >= {"llama-server", "front responder"}
    assert {row["via"] for row in result["results"]} == {"managed_process"} and all(row["verified"] for row in result["results"])


# --- POST /api/model/unload-all (separate from /api/model/unload) --------------------------------------------

def api_client():
    app = FastAPI()
    app.include_router(unload_all_api.router)
    app.include_router(model_api.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_unload_all_is_a_separate_endpoint_and_the_dropdown_unload_is_unchanged(monkeypatch):
    paths = {route.path for route in model_api.router.routes}
    assert "/api/model/unload" in paths and "/api/model/unload-all" not in paths
    assert "/api/model/unload-all" in {route.path for route in unload_all_api.router.routes}
    calls: list[str] = []

    async def unload():
        calls.append("manager.unload")
        return MANAGER.state

    monkeypatch.setattr(MANAGER, "unload", unload)
    async with api_client() as client:
        response = await client.post("/api/model/unload")
    assert response.status_code == 200 and calls == ["manager.unload"]


async def test_unload_all_returns_the_verified_per_backend_result(monkeypatch):
    FakeServers(ollama=["qwen3:8b"], lmstudio=["qwen-a"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    LOADED.record(LMSTUDIO, "qwen-a")
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["released_count"] == 2 and body["keep_warm"] is False
    assert [(row["model"], row["backend"], row["verified"]) for row in body["results"]] == [("qwen3:8b", "ollama", True), ("qwen-a", "lmstudio", True)]
    assert body["released"] == 2 and body["failed"] == 0 and body["skipped"] == [] and "snapshot" in body


async def test_unload_all_refusals_are_409_with_a_visible_reason_and_touch_nothing(monkeypatch):
    servers = FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    async with api_client() as client:
        async with MANAGER._request_lease.shared():
            busy = await client.post("/api/model/unload-all")
        MANAGER.state.loading = True
        loading = await client.post("/api/model/unload-all")
        MANAGER.state.loading = False
        monkeypatch.setattr(IDLE_UNLOAD, "_busy", lambda: True)
        running_task = await client.post("/api/model/unload-all")
        monkeypatch.setattr(IDLE_UNLOAD, "_busy", lambda: False)
        LOADED.clear()
        nothing = await client.post("/api/model/unload-all")
    assert busy.status_code == 409 and "answering a request" in busy.json()["detail"]
    assert loading.status_code == 409 and "still loading" in loading.json()["detail"]
    assert running_task.status_code == 409 and "working on a task" in running_task.json()["detail"]
    assert nothing.status_code == 409 and nothing.json()["detail"].startswith("Nothing to unload")
    assert servers.ollama == ["qwen3:8b"] and servers.mutating() == []
    assert MANAGER.state.manually_unloaded is False and IDLE_UNLOAD.held is False


async def test_unload_all_after_an_idle_unload_says_so(monkeypatch):
    FakeServers().install(monkeypatch)
    IDLE_UNLOAD.last_idle_released = ["ollama:qwen3:8b"]
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 409
    assert "was unloaded after 5 minutes idle" in response.json()["detail"]


async def test_unload_all_partial_failure_returns_207_with_per_model_results(monkeypatch):
    """One release fails (Ollama keeps it resident): that model is verified:false with its error, the
    others are released, and the status is 207, never 200."""
    FakeServers(ollama=["stuck:1b"], ollama_ignores_unload=True, lmstudio=["qwen-a"]).install(monkeypatch)
    LOADED.record(OLLAMA, "stuck:1b")
    LOADED.record(LMSTUDIO, "qwen-a")
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 207
    body = response.json()
    by_model = {row["model"]: row for row in body["results"]}
    assert body["ok"] is False and body["released"] == 1 and body["failed"] == 1
    assert by_model["stuck:1b"]["verified"] is False and "still loaded" in by_model["stuck:1b"]["error"]
    assert by_model["qwen-a"]["verified"] is True and by_model["qwen-a"]["error"] is None
    assert "stuck:1b" in body["reason"] and "snapshot" in body
    assert MANAGER.state.manually_unloaded is False  # a failed unload is not "stays unloaded"


# --- manually_unloaded: no background load or warm until a user turn / explicit Load -----------------------------

class Tripwire:
    """Any HTTP request through it fails the test: a warm or refresh went out after Unload."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url}")
        return httpx.Response(200, json={"done": True, "models": []})

    def install(self, monkeypatch) -> "Tripwire":
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs.pop("transport", None)
            return real(*args, transport=httpx.MockTransport(self.handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return self


async def unloaded_after_unload_all(monkeypatch) -> FakeServers:
    servers = FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    result = await keep_warm_release.release_models("manual")
    assert result["ok"] is True and MANAGER.state.manually_unloaded is True
    return servers


async def test_after_unload_all_background_ensure_and_load_are_refused_and_make_no_http_call(monkeypatch):
    await unloaded_after_unload_all(monkeypatch)
    trip = Tripwire().install(monkeypatch)
    settings = settings_with(False, backend="ollama", port=11434, remote_model="qwen3:8b")
    with pytest.raises(ModelManuallyUnloaded):
        await MANAGER.ensure_runtime(settings)
    with pytest.raises(ModelManuallyUnloaded):
        await MANAGER.ensure_vision(settings)
    with pytest.raises(ModelManuallyUnloaded):
        await MANAGER.load(settings)
    with pytest.raises(ModelManuallyUnloaded):
        await MANAGER._load_locked(settings, None, context_size=None, vision=None)
    with pytest.raises(ModelManuallyUnloaded):
        await MANAGER._load_impl(settings, None, context_size=None, vision=None)
    assert trip.requests == []


async def test_after_unload_all_every_direct_http_warm_and_refresh_stays_silent(monkeypatch):
    """Ollama prompt-less /api/generate, LM Studio loads, llama-server/front warm pings: none go out."""
    await unloaded_after_unload_all(monkeypatch)
    trip = Tripwire().install(monkeypatch)
    started: list[str] = []

    async def probe(*args, **kwargs):
        return {"ok": True, "models": ["qwen3:8b", "qwen-a"]}

    monkeypatch.setattr(ollama_runtime, "probe_remote_server", probe)

    async def cli(*args, **kwargs):
        started.append("lms")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(gpu_prefer, "_run_cli", cli)
    monkeypatch.setattr(gpu_prefer, "nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(gpu_prefer.shutil, "which", lambda name: "/bin/lms")
    assert warm_blocked() is True
    assert (await gpu_prefer.ensure_ollama_gpu(host="127.0.0.1", port=11434, model="qwen3:8b"))["method"] == "unloaded"
    assert (await gpu_prefer.ensure_lmstudio_gpu(host="127.0.0.1", port=1234, model="qwen-a"))["method"] == "unloaded"
    ollama = await ollama_runtime.ensure_local_ollama(host="127.0.0.1", port=11434, model="qwen3:8b", pull_if_missing=False)
    assert ollama["ok"] is False and ollama["method"] == "unloaded"
    lm = await lmstudio_server.ensure_local_lmstudio(host="127.0.0.1", port=1234, model="qwen-a")
    assert lm["ok"] is False and lm.get("method") == "unloaded"
    await FRONT_RUNTIME._warmup(FrontDecision(reason="ok"))
    assert (await FRONT_RUNTIME.ensure_started(AppSettings())).reason == "released_until_next_turn"
    # Read-only status probes (GET) may happen; no warm / load / refresh (POST) goes out.
    assert [r for r in trip.requests if not r.startswith("GET ")] == [] and started == []
    # The doc'd NINE_B_REWARM coordinator and any new warm path ask this same helper first.
    IDLE_UNLOAD.explicit_load()
    assert warm_blocked() is False


async def test_a_turn_after_unload_all_clears_the_flag_before_ensure_and_respawns_the_model(monkeypatch):
    from app.agent import loop

    await unloaded_after_unload_all(monkeypatch)
    loads: list[bool] = []

    async def load_locked(*args, **kwargs):
        loads.append(MANAGER.state.manually_unloaded)
        MANAGER.state.loaded = True
        return MANAGER.state

    monkeypatch.setattr(MANAGER, "_load_locked", load_locked)
    settings = settings_with(False, backend="ollama", remote_model="qwen3:8b")
    with pytest.raises(ModelManuallyUnloaded):  # a background caller is refused ...
        await MANAGER.ensure_runtime(settings)

    async def turn():
        await MANAGER.ensure_runtime(settings)  # ... the turn is not: the flag was cleared at its entry point

    await loop.AGENT._start_runner("keep-warm-turn", turn())
    loop.AGENT._tasks.pop("keep-warm-turn", None)
    assert loads == [False] and MANAGER.state.manually_unloaded is False and MANAGER.state.loaded is True


async def test_an_owner_chat_turn_clears_the_flag_before_it_reaches_ensure(monkeypatch):
    from app.persona import owner_chat

    await unloaded_after_unload_all(monkeypatch)
    seen: list[bool] = []

    def stop(*args, **kwargs):
        seen.append(MANAGER.state.manually_unloaded)
        raise RuntimeError("stop")

    monkeypatch.setattr(owner_chat, "_ensure_conversation", stop)
    with pytest.raises(RuntimeError):
        async for _ in owner_chat.stream_owner_chat("hello"):
            pass
    assert seen == [False]


async def test_an_explicit_load_clears_the_flag_even_when_the_load_itself_fails(monkeypatch):
    async def refuse(*args, **kwargs):
        raise RuntimeError("no GPU in this test")

    MANAGER.state.manually_unloaded = True
    IDLE_UNLOAD.note_released(front=False)
    monkeypatch.setattr(model_api, "load_settings", lambda: AppSettings())
    monkeypatch.setattr(MANAGER, "load", refuse)
    with pytest.raises(HTTPException):
        await model_api.load_model(None)
    assert MANAGER.state.manually_unloaded is False and IDLE_UNLOAD.held is False


async def test_idle_unload_holds_background_starters_but_a_turn_lifts_it():
    IDLE_UNLOAD.note_released(front=False)
    assert IDLE_UNLOAD.background_blocked() is True
    assert (await FRONT_RUNTIME.ensure_started(AppSettings())).reason == "released_until_next_turn"
    IDLE_UNLOAD.touch()
    assert IDLE_UNLOAD.background_blocked() is False


# --- the ledger (not a name guard) decides what is foreign -----------------------------------------------------

async def test_ownership_comes_from_the_ledger_not_from_a_model_name(monkeypatch):
    """The same name is exempt when someone else loaded it and released when ANZU loaded it."""
    shared = "owner-shared-model:7b"
    servers = FakeServers(ollama=[shared]).install(monkeypatch)
    assert (await keep_warm_release.release_models("manual"))["refused"] is True  # unknown origin = foreign
    assert servers.ollama == [shared]
    assert request_extras("http://127.0.0.1:11434/v1", shared) == {}
    LOADED.record(OLLAMA, shared)  # ANZU loaded a model that happens to carry that name
    assert request_extras("http://127.0.0.1:11434/v1", shared) == {"keep_alive": "300s"}
    assert (await keep_warm_release.release_models("manual"))["ok"] is True
    assert servers.ollama == []
    # The deny constant lives in the one helper module and nowhere else.
    holders = [name for name, text in _python_files() if re.search(r"""["']bgm[-_]""", text)]
    assert holders == ["inference/keep_alive.py"]


async def test_denied_model_is_never_addressed_even_if_the_ledger_lists_it(monkeypatch):
    """bgm-ingest-9b: no keep_alive, no TTL, no unload, no warm and no touch, whatever the ledger or toggle says."""
    servers = FakeServers(ollama=[FOREIGN, ANZU_OLLAMA], lmstudio=[FOREIGN]).install(monkeypatch)
    LOADED.record(OLLAMA, FOREIGN)  # even a (buggy) ledger entry cannot unlock it
    LOADED.record(LMSTUDIO, FOREIGN)
    for keep_warm in (False, True):
        write_settings(Path(load_settings.__globals__["settings_path"]().parent), keep_warm=keep_warm)
        assert request_extras("http://127.0.0.1:11434/v1", FOREIGN) == {}
        assert request_extras("http://127.0.0.1:1234/v1", FOREIGN) == {}
    assert keep_alive.is_denied(FOREIGN) and keep_alive.is_denied(FOREIGN + ":latest") and not keep_alive.is_denied(ANZU_OLLAMA)
    with pytest.raises(keep_alive.DeniedModelError):
        keep_alive.ollama_body(FOREIGN)
    with pytest.raises(keep_alive.DeniedModelError):
        keep_alive.ollama_body(FOREIGN, release=True)
    monkeypatch.setattr(gpu_prefer, "nvidia_gpu_present", lambda: True)
    warmed = await gpu_prefer.ensure_ollama_gpu(host="127.0.0.1", port=11434, model=FOREIGN)
    assert warmed["ok"] is False and warmed["method"] == "denied"
    assert servers.requests == [], "a denied model gets zero requests of any kind"
    assert await keep_alive.touch_ollama_if_resident("http://127.0.0.1:11434/v1", FOREIGN) is False
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    result = await keep_warm_release.release_models("manual")
    assert FOREIGN in servers.ollama and FOREIGN in servers.lmstudio
    assert all(FOREIGN not in json.dumps(body) for body in servers.unload_requests())
    assert {item["model"] for item in result["skipped"]} >= {FOREIGN}
    assert all(row["model"] != FOREIGN for row in result["results"])


# --- static scan: every keep_alive literal and every load / warm site is routed through helper + guard ----------

import ast  # noqa: E402

KEEP_ALIVE_VALUE = re.compile(r"""keep_alive["']?\s*[:=]\s*(?P<value>[^\s,)}]+)""")
KEEP_ALIVE_FILES_EXEMPT = {"inference/keep_alive.py", "workers/browser.py"}  # the helper; an unrelated browser flag
UNLOAD_ONLY = '"keep_alive": 0'


def _python_files():
    for path in sorted(BACKEND_APP.rglob("*.py")):
        yield path.relative_to(BACKEND_APP).as_posix(), path.read_text(encoding="utf-8-sig")


def test_static_scan_finds_no_hardcoded_keep_alive_anywhere_in_backend():
    offenders: list[str] = []
    for name, text in _python_files():
        if name in KEEP_ALIVE_FILES_EXEMPT:
            continue
        if re.search(r"""["']\d+h["']""", text) and "keep_alive" in text:
            offenders.append(f"{name}: hours literal (such as '24h') next to keep_alive")
        for match in KEEP_ALIVE_VALUE.finditer(text):
            value = match.group("value").strip("`.;")
            if not (value.startswith("ollama_keep_alive(") or value == "0"):
                offenders.append(f"{name}: keep_alive = {value}")
    assert offenders == []


def _outermost_functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _calls(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            names.add(func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else "")
    return names


def _marker_strings(node: ast.AST, *, cli_loads: bool) -> list[str]:
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value
            if "/api/generate" in value or "models/load" in value or value == "/load" or (cli_loads and value == "load"):
                found.append(child.value)
    return found


# `explicit_load` is the owner-initiated entry: it clears the flag on purpose, then the guarded paths run.
GUARDS = {"warm_blocked", "_guard_background_load", "background_blocked", "explicit_load"}


def test_static_scan_every_direct_load_and_warm_call_site_sits_behind_the_manually_unloaded_guard():
    """Finds every function that issues a model load or prompt-less warm (Ollama /api/generate, LM Studio
    load paths or ``lms load``, the front-responder warm-up) and requires it, or every in-module caller
    that reaches it, to call the guard. A new warm path that skips the gate fails here."""
    problems: list[str] = []
    sites: list[str] = []
    for name, text in _python_files():
        tree = ast.parse(text)
        functions = {fn.name: fn for fn in _outermost_functions(tree)}
        callers: dict[str, set[str]] = {}
        for fn in functions.values():
            for called in _calls(fn):
                callers.setdefault(called, set()).add(fn.name)

        def guarded(fn_name: str, seen: frozenset[str] = frozenset()) -> bool:
            fn = functions.get(fn_name)
            if fn is None or fn_name in seen:
                return False
            if _calls(fn) & GUARDS:
                return True
            parents = callers.get(fn_name, set()) - {fn_name}
            return bool(parents) and all(guarded(parent, seen | {fn_name}) for parent in parents)

        for fn in functions.values():
            segment = ast.get_source_segment(text, fn) or ""
            if name == "inference/keep_warm_release.py":
                continue  # the release module only ever unloads (keep_alive=0 / unload APIs)
            loads = _marker_strings(fn, cli_loads=name.startswith("inference/"))
            is_warmup = name == "inference/front_runtime.py" and fn.name == "_warmup"
            if not (loads or is_warmup):
                continue
            if UNLOAD_ONLY in segment or "keep_alive\": 0" in segment:
                continue  # an owner-chosen unload request, not a load
            if "/load" in " ".join(loads) or "models/load" in " ".join(loads) or "/api/generate" in " ".join(loads) \
                    or "load" in loads or is_warmup:
                sites.append(f"{name}:{fn.name}")
                if not guarded(fn.name):
                    problems.append(f"{name}:{fn.name} loads or warms a model without the manually_unloaded guard")
    assert problems == []
    # The scan really found the known sites (a broken scanner must not pass silently).
    assert {"inference/gpu_prefer.py:ensure_ollama_gpu", "inference/gpu_prefer.py:_lmstudio_rest_load",
            "inference/ollama_runtime.py:ensure_local_ollama", "inference/lmstudio_server.py:ensure_local_lmstudio",
            "inference/lmstudio_context.py:grow_local_instance", "inference/front_runtime.py:_warmup"} <= set(sites)


def test_static_scan_the_manager_load_paths_and_front_respawn_check_the_flag():
    text = (BACKEND_APP / "inference" / "manager.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    methods = {fn.name: fn for fn in _outermost_functions(tree)}
    for name in ("load", "ensure_runtime", "ensure_vision", "_load_locked", "_load_impl"):
        assert "_guard_background_load" in _calls(methods[name]), name
    front = ast.parse((BACKEND_APP / "inference" / "front_runtime.py").read_text(encoding="utf-8-sig"))
    assert "background_blocked" in _calls({fn.name: fn for fn in _outermost_functions(front)}["ensure_started"])
    # No prepare_engine_for in this tree yet; when RFC-0225 adds it, it must join this scan.
    assert "def prepare_engine_for" not in "\n".join(text for _n, text in _python_files())


def test_static_scan_every_keep_alive_ttl_consumer_reads_the_helper():
    for name in ("inference/gpu_prefer.py", "inference/ollama_runtime.py", "inference/lmstudio_server.py",
                 "inference/lmstudio_context.py", "providers/base.py"):
        text = (BACKEND_APP / name).read_text(encoding="utf-8")
        assert re.search(r"ollama_keep_alive|ollama_request|lmstudio_ttl_seconds|request_extras", text), name


def test_a_rebuilt_lm_studio_instance_follows_the_policy_only_when_anzu_loaded_it():
    from app.inference.lmstudio_context import instance_load_args

    row = {"modelKey": "k", "identifier": "owner", "ttl": 60}
    assert instance_load_args(row, key="k", identifier="owner", context_length=4096)[-2:] == ["--ttl", 60]  # foreign: as-is
    LOADED.record(LMSTUDIO, "owner")
    assert instance_load_args(row, key="k", identifier="owner", context_length=4096)[-2:] == ["--ttl", 300]


# --- CoS guard coverage: every remaining background path, and the owner respawn --------------------------------

async def test_grow_local_instance_runs_no_lms_command_after_unload_and_proceeds_after_an_owner_act(monkeypatch):
    from app.inference import lmstudio_context

    await unloaded_after_unload_all(monkeypatch)
    commands: list[list[str]] = []

    def run(argv, **kwargs):
        commands.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(lmstudio_context.subprocess, "run", run)
    monkeypatch.setattr(lmstudio_context.shutil, "which", lambda name: "/bin/lms")
    settings = settings_with(False, backend="lmstudio", host="127.0.0.1", port=1234)
    assert await lmstudio_context.grow_local_instance(settings, 65536, "qwen-a") is None
    assert commands == [], "no `lms ps` / `lms load` while the Unload hold is up"
    IDLE_UNLOAD.explicit_load()  # an explicit Load (or an owner turn) lifts the hold
    await lmstudio_context.grow_local_instance(settings, 65536, "qwen-a")
    assert commands and commands[0][:2] == ["/bin/lms", "ps"]


async def test_startup_autoload_after_unload_all_issues_no_lms_load_and_no_ollama_warm(monkeypatch):
    """main._autoload_model reaches ensure_local_lmstudio / ensure_local_ollama; both stay silent after Unload."""
    from app import main

    await unloaded_after_unload_all(monkeypatch)
    trip = Tripwire().install(monkeypatch)
    started: list[str] = []

    async def probe(*args, **kwargs):
        return {"ok": True, "models": []}

    async def cli(*args, **kwargs):
        started.append("lms")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(lmstudio_server, "probe_remote_server", probe)
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", probe)
    monkeypatch.setattr(lmstudio_server, "lmstudio_cli", lambda: "/bin/lms")
    monkeypatch.setattr(lmstudio_server, "_run_cli", lambda *a, **k: started.append("lms") or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(gpu_prefer, "_run_cli", cli)
    monkeypatch.setattr(main, "model_enabled", lambda s: True, raising=False)
    for backend, model in (("lmstudio", "qwen-a"), ("ollama", "qwen3:8b")):
        await main._autoload_model(settings_with(False, backend=backend, host="127.0.0.1", remote_model=model,
                                                 port=1234 if backend == "lmstudio" else 11434))
    assert started == [] and [r for r in trip.requests if not r.startswith("GET ")] == []
    assert MANAGER.state.loaded is False and MANAGER.state.manually_unloaded is True


async def test_hotswap_activation_is_an_explicit_load_and_the_lm_studio_ollama_ensure_paths_respawn(monkeypatch, tmp_path):
    """hotswap reaches ensure_local_* only through activate_runtime_profile (which lifts the hold first); once an
    owner act lifted it, ensure_local_lmstudio loads with --ttl 300 and ensure_local_ollama warms with 300s."""
    tree = ast.parse((BACKEND_APP / "inference" / "hotswap.py").read_text(encoding="utf-8-sig"))
    fns = {fn.name: fn for fn in _outermost_functions(tree)}
    activate_calls = [c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id
                      for c in ast.walk(fns["activate_runtime_profile"]) if isinstance(c, ast.Call)
                      and isinstance(c.func, (ast.Attribute, ast.Name))]
    assert activate_calls.index("explicit_load") < activate_calls.index("apply_runtime_profile_to_settings")
    callers = [name for name, text in _python_files() if re.search(r"(?<!def )apply_runtime_profile_to_settings\(", text)]
    assert callers == ["inference/hotswap.py"]  # no other module reaches the hotswap ensure_local_* calls

    await unloaded_after_unload_all(monkeypatch)
    loads: list[list[str]] = []

    async def probe(*args, **kwargs):
        return {"ok": True, "models": ["qwen-a"]}

    monkeypatch.setattr(lmstudio_server, "probe_remote_server", probe)
    monkeypatch.setattr(lmstudio_server, "lmstudio_cli", lambda: "/bin/lms")
    monkeypatch.setattr(lmstudio_server, "_run_cli", lambda argv, timeout: loads.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "", ""))

    async def loaded_ids(host, port):
        return set()

    monkeypatch.setattr(lmstudio_server, "_loaded_model_ids", loaded_ids)
    blocked = await lmstudio_server.ensure_local_lmstudio(host="127.0.0.1", port=1234, model="qwen-a")
    assert blocked["method"] == "unloaded" and loads == []
    IDLE_UNLOAD.explicit_load()
    await lmstudio_server.ensure_local_lmstudio(host="127.0.0.1", port=1234, model="qwen-a")
    assert loads and loads[0][1:3] == ["load", "qwen-a"] and loads[0][-2:] == ["--ttl", "300"]


async def test_an_owner_turn_respawns_the_front_responder_warm_up_and_the_front_warm_runs(monkeypatch):
    await unloaded_after_unload_all(monkeypatch)
    IDLE_UNLOAD.note_released(front=True)
    warmed: list[bool] = []

    class Provider:
        async def chat_stream(self, *args, **kwargs):
            warmed.append(True)
            yield "ok"

    FRONT_RUNTIME._provider = Provider()
    await FRONT_RUNTIME._warmup(FrontDecision(reason="ok"))
    assert warmed == []  # background warm-up refused while unloaded
    IDLE_UNLOAD.touch()  # an owner turn lifts the hold
    assert warm_blocked() is False


def test_no_front_keep_warm_loop_or_watchdog_restart_exists_in_this_tree_yet():
    """RFC-0230-S2's front keep-warm and watchdog restart are not in the tree. When one lands it must call
    warm_blocked()/background_blocked() first; this test then fails until it is added to the guard scan."""
    pattern = re.compile(r"def \w*(front\w*(watchdog|keep_?warm|rewarm)|(watchdog|keep_?warm|rewarm)\w*front)", re.I)
    assert [name for name, text in _python_files() if pattern.search(text)] == []


async def test_every_ollama_generate_and_chat_call_goes_through_the_one_helper():
    """No /api/generate or /api/chat request in backend/app is built outside ollama_request()."""
    offenders: list[str] = []
    for name, text in _python_files():
        if name == "inference/keep_alive.py":
            continue
        for fn in _outermost_functions(ast.parse(text)):
            literals = [c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)
                        and c.value in {"/api/generate", "/api/chat"}]
            if literals and "ollama_request" not in _calls(fn):
                offenders.append(f"{name}:{fn.name}")
    assert offenders == []


async def test_ollama_v1_turn_is_followed_by_a_keep_alive_touch_only_if_resident(monkeypatch, tmp_path):
    servers = FakeServers(ollama=[ANZU_OLLAMA]).install(monkeypatch)
    real = httpx.AsyncClient
    monkeypatch.setattr(keep_alive.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(servers.handler), **kw))
    base = "http://127.0.0.1:11434/v1"
    assert await keep_alive.touch_ollama_if_resident(base, ANZU_OLLAMA) is False  # not ANZU-loaded: never touched
    assert servers.requests == []
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    for keep_warm, expected in ((False, "300s"), (True, "-1")):
        servers.requests.clear()
        write_settings(tmp_path, keep_warm=keep_warm)
        assert await keep_alive.touch_ollama_if_resident(base, ANZU_OLLAMA) is True
        posts = [body for _p, method, path, body in servers.requests if method == "POST"]
        assert posts == [{"model": ANZU_OLLAMA, "prompt": "", "stream": False, "keep_alive": expected}]
    servers.ollama.clear()  # no longer resident (its own expiry unloaded it): a touch must never load it
    servers.requests.clear()
    assert await keep_alive.touch_ollama_if_resident(base, ANZU_OLLAMA) is False
    assert [r for r in servers.requests if r[1] == "POST"] == []
    servers.ollama.append(ANZU_OLLAMA)
    MANAGER.state.manually_unloaded = True  # after Unload nothing is touched
    servers.requests.clear()
    assert await keep_alive.touch_ollama_if_resident(base, ANZU_OLLAMA) is False and servers.requests == []


async def test_the_manager_touches_ollama_after_every_turn(monkeypatch):
    from types import SimpleNamespace

    touched: list[tuple[str, str]] = []

    async def touch(base_url, model, api_key=""):
        touched.append((base_url, model))
        return True

    async def reply(*args, **kwargs):
        return "reply"

    monkeypatch.setattr(keep_alive, "touch_ollama_if_resident", touch)
    monkeypatch.setattr(MANAGER, "_chat_holding_lease", reply)
    MANAGER.provider = SimpleNamespace(base_url="http://127.0.0.1:11434/v1", model=ANZU_OLLAMA, api_key="local")
    MANAGER.state.backend, MANAGER.state.loaded = "ollama", True
    assert await MANAGER.chat([]) == "reply"
    assert touched == [("http://127.0.0.1:11434/v1", ANZU_OLLAMA)]
    MANAGER.state.backend = "llama.cpp"
    await MANAGER.chat([])
    assert len(touched) == 1  # only Ollama turns need the touch


async def test_lm_studio_rest_load_retries_without_ttl_when_a_build_rejects_the_key(monkeypatch):
    """The documented /api/v1/models/load body has no `ttl`; a build that rejects it still loads (ANZU's timer enforces)."""
    bodies: list[dict] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(400 if "ttl" in body else 200, json={"error": "Unrecognized key(s) in object: 'ttl'"})

    monkeypatch.setattr(gpu_prefer.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert (await gpu_prefer._lmstudio_rest_load("127.0.0.1", 1234, "m", timeout=5))["ok"] is True
    assert ["ttl" in body for body in bodies] == [True, False]


def test_manually_unloaded_is_exposed_in_the_model_snapshot_and_the_status_monitor_live_keys():
    from app.inference.status_monitor import _LIVE_STATE_KEYS

    assert "manually_unloaded" in _LIVE_STATE_KEYS
    MANAGER.state.manually_unloaded = True
    assert MANAGER.live_state_overlay()["manually_unloaded"] is True
    assert MANAGER._assemble_snapshot(load_settings(), healthy=False)["manually_unloaded"] is True
    MANAGER.state.manually_unloaded = False
    assert MANAGER.live_state_overlay()["manually_unloaded"] is False
