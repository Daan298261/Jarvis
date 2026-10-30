from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config import AppSettings
from app.engine_mode import ModelDisabledError


@pytest.fixture
def engines(jarvis_env, monkeypatch):
    from app.decision import cache
    settings = jarvis_env["settings"]
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.api.settings.load_settings", lambda: settings)
    monkeypatch.setattr("app.api.settings.save_settings", Mock())
    monkeypatch.setattr("app.persona.owner_chat.load_settings", lambda: settings)
    cache.clear()
    yield settings
    cache.clear()


@pytest.mark.asyncio
async def test_modes_roundtrip_without_changing_provider_preferences(engines):
    from app.api.settings import SettingsUpdate, get_settings, update_settings
    engines.inference.profile = "fast"
    engines.decision.tier = "jev_optional"
    engines.decision.laya_enabled = True
    original = engines.model_dump()
    for mode in ("model_only", "reflex_only", "hybrid"):
        saved = await update_settings(SettingsUpdate(engine_mode=mode))
        assert saved["engine_mode"] == mode
        assert (await get_settings())["engine_mode"] == mode
        assert saved["inference"] == original["inference"]
        assert saved["decision"] == original["decision"]
        assert saved["front_responder"] == original["front_responder"]
    with pytest.raises(ValidationError):
        SettingsUpdate(engine_mode="off")
    assert AppSettings().engine_mode == "hybrid"


@pytest.mark.asyncio
async def test_reflex_only_blocks_model_entrypoints_and_explicit_front_provider(engines, monkeypatch):
    from app.agent.front_responder import generate_front_reply
    from app.inference.front_runtime import FrontRuntime
    from app.inference.manager import InferenceManager
    from app.providers.base import ChatMessage
    engines.engine_mode = "reflex_only"
    manager = InferenceManager()
    provider = SimpleNamespace(chat=AsyncMock(), chat_stream=Mock())
    manager.provider = provider
    for action in (
        manager.chat([ChatMessage(role="user", content="Explain rain")], settings=engines),
        manager.load(engines),
        manager.ensure_runtime(engines),
    ):
        with pytest.raises(ModelDisabledError):
            await action
    with pytest.raises(ModelDisabledError):
        async for _ in manager.chat_stream([ChatMessage(role="user", content="Hello")], settings=engines):
            pass
    provider.chat.assert_not_awaited()
    provider.chat_stream.assert_not_called()
    front = await generate_front_reply("Explain rain", settings=engines, provider=provider)
    assert front.skipped and not front.text
    runtime = FrontRuntime()
    monkeypatch.setattr(runtime, "_start_local", AsyncMock(side_effect=AssertionError("Must not load front")))
    assert (await runtime.ensure_started(engines)).reason == "reflex_only"
    assert runtime.provider(engines) is None


def _adapter(name, available=True):
    from app.decision.types import Answer, DecisionResult
    return SimpleNamespace(VERSION="test", available=Mock(return_value=(available, "not enabled")),
                           decide=Mock(return_value=DecisionResult(
                               answers={"tool_select": Answer("tool_select", "choice", "filesystem", 1.0)},
                               source=name, provider=name, decision_class="tool_selection")))


@pytest.mark.parametrize("mode,expected", [("hybrid", "laya"), ("model_only", "generative"), ("reflex_only", "laya")])
def test_selected_mode_filters_decision_providers(engines, monkeypatch, mode, expected):
    from app.decision import reflex
    engines.engine_mode = mode
    adapters = {name: _adapter(name) for name in ("laya", "jev", "generative")}
    monkeypatch.setattr(reflex, "_ADAPTERS", adapters)
    monkeypatch.setattr(reflex.laya_runtime, "is_ready", lambda: True)
    result = reflex.decide({"user_message": "Read a file"},
                           {"tool_select": {"type": "choice", "question": "Which tool?", "choices": ["filesystem", "browser"]}},
                           "tool_selection", 1000, "allow_cloud", use_cache=False)
    assert result.provider == expected
    if mode == "model_only":
        adapters["laya"].available.assert_not_called()
        adapters["jev"].available.assert_not_called()
    if mode == "reflex_only":
        adapters["generative"].available.assert_not_called()


def test_reflex_only_never_falls_back_to_generative_when_typed_providers_missing(engines, monkeypatch):
    from app.decision import reflex
    engines.engine_mode = "reflex_only"
    adapters = {"laya": _adapter("laya", False), "jev": _adapter("jev", False), "generative": _adapter("generative")}
    monkeypatch.setattr(reflex, "_ADAPTERS", adapters)
    monkeypatch.setattr(reflex.laya_runtime, "is_ready", lambda: True)
    monkeypatch.setattr(reflex.generative, "decide", Mock(side_effect=AssertionError("Generative fallback is off")))
    result = reflex.decide({"user_message": "Read a file"},
                           {"tool_select": {"type": "choice", "question": "Which tool?", "choices": ["filesystem", "browser"]}},
                           "tool_selection", 1000, "allow_cloud", use_cache=False)
    assert result.provider == "rules" and result.fallback_used
    adapters["generative"].decide.assert_not_called()


@pytest.mark.parametrize("mode", ["hybrid", "model_only", "reflex_only"])
def test_hard_approval_requirement_survives_every_mode(engines, mode):
    from app.decision.reflex import decide
    engines.engine_mode = mode
    result = decide({"user_message": "Change a file", "policy_requires_approval": True},
                    {"approval_needed": {"type": "noul", "question": "Approval required?"}},
                    "approval_signal", 1000, "local_only", use_cache=False)
    assert float(result.answers["approval_needed"].value) >= .99


@pytest.mark.asyncio
async def test_reflex_only_chat_does_not_delegate_or_run_model(engines, monkeypatch):
    from app.persona.owner_chat import stream_owner_chat, reset_owner_conversations
    engines.engine_mode = "reflex_only"
    delegate = AsyncMock(side_effect=AssertionError("No hidden model task"))
    monkeypatch.setattr("app.agent.loop.AGENT.create_task", delegate)
    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", AsyncMock(side_effect=AssertionError("No front generation")))
    reset_owner_conversations()
    events = [event async for event in stream_owner_chat("Write a detailed report and save it to disk")]
    done = next(event for event in events if event["type"] == "done")
    assert done["engine_mode"] == "reflex_only"
    assert "no requested work was run" in done["reply"]
    delegate.assert_not_awaited()
    reset_owner_conversations()


@pytest.mark.asyncio
async def test_reflex_only_task_finishes_with_bounded_reply_without_model(engines, jarvis_env, monkeypatch):
    from app.agent.loop import AgentRuntime
    from app.db.models import Task
    from app.db.session import SessionLocal
    engines.engine_mode = "reflex_only"
    monkeypatch.setattr(jarvis_env["manager"], "load", AsyncMock(side_effect=AssertionError("No model load")))
    runtime = AgentRuntime()
    task = await runtime.create_task("Write a detailed report and save it to disk")
    await runtime._tasks[task.id]
    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row.status == "completed"
        assert "no requested work was run" in row.result


@pytest.mark.asyncio
async def test_reflex_only_startup_skips_model_load(engines, monkeypatch):
    from app.main import _autoload_model
    engines.engine_mode = "reflex_only"
    load = AsyncMock(side_effect=AssertionError("Autoload must be skipped"))
    monkeypatch.setattr("app.main.MANAGER.load", load)
    await _autoload_model(engines)
    load.assert_not_awaited()


def test_model_only_blocks_direct_typed_provider_calls_and_laya_startup(engines, monkeypatch):
    from app.decision.jev_client import JevHttpError, post_systemone
    from app.decision.laya import runtime
    engines.engine_mode = "model_only"
    assert runtime.restore_on_startup() is None
    with pytest.raises(RuntimeError, match="bypassed"):
        runtime.enable()
    with pytest.raises(RuntimeError, match="bypassed"):
        runtime.decide_local(state={}, questions=[], decision_class="request_routing", deadline_ms=50)
    with pytest.raises(JevHttpError, match="bypassed"):
        post_systemone(api_key="fixture", state={}, questions={})


def test_engine_mode_persists_in_saved_settings(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / "defaults.json")
    for mode in ("model_only", "reflex_only", "hybrid"):
        config.save_settings(AppSettings(engine_mode=mode))
        assert config.load_settings().engine_mode == mode


@pytest.mark.asyncio
async def test_reflex_only_load_controls_cannot_start_external_runtime(engines, monkeypatch):
    from fastapi import HTTPException
    from app.api import model
    from app.inference import hotswap, running_models
    from app.inference.runtime_profiles import RuntimeProfile
    engines.engine_mode = "reflex_only"
    monkeypatch.setattr(model, "load_settings", lambda: engines)
    monkeypatch.setattr(hotswap, "load_settings", lambda: engines)
    monkeypatch.setattr(running_models, "load_settings", lambda: engines)
    probe = AsyncMock(side_effect=AssertionError("No runtime probe/start"))
    monkeypatch.setattr(hotswap, "probe_remote_server", probe)
    profile = RuntimeProfile(id="test", name="test", label="Test", model="test", provider="lmstudio",
                             endpoint="http://127.0.0.1:1234/v1", context_limit=4096,
                             quantization="Q4", privacy_class="local", cost_ceiling_usd=None)
    with pytest.raises(ModelDisabledError):
        await hotswap.activate_runtime_profile(profile)
    with pytest.raises(ModelDisabledError):
        await hotswap.apply_runtime_profile_to_settings(profile)
    with pytest.raises(ModelDisabledError):
        await running_models.RUNNING_MODELS.decide("missing", "use")
    with pytest.raises(HTTPException) as error:
        await model.load_model()
    assert error.value.status_code == 409
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_with_literal_reply_cannot_claim_work_ran_in_reflex_only(engines):
    from app.engine_mode import reflex_only_reply
    engines.engine_mode = "reflex_only"
    reply, _ = await reflex_only_reply("Write a file C:/result.txt and reply only 'Done'", engines)
    assert "no requested work was run" in reply
