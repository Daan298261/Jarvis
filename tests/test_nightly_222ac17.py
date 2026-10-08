"""Nightly 222ac17: real provider, context budget, memory grant, and model-switch paths.

These tests do not mock the methods that failed on the desktop. The HTTP client
under the provider is a stub; chat_stream itself is the production class.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.providers.base import ChatMessage, StreamStallError

ROOT = Path(__file__).resolve().parents[1]


class _Delta:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning_content = None


class _Choice:
    def __init__(self, content: str) -> None:
        self.delta = _Delta(content)
        self.finish_reason = "stop"


class _Chunk:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _Stream:
    def __init__(self, content: str) -> None:
        self._content = content
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return _Chunk(self._content)


class _Completions:
    def __init__(self, *, stall: bool = False, content: str = "ready") -> None:
        self.stall = stall
        self.content = content
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.stall:
            await asyncio.sleep(5)
        return _Stream(self.content)


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _Client:
    def __init__(self, completions: _Completions) -> None:
        self.chat = _Chat(completions)


@pytest.mark.asyncio
async def test_real_provider_accepts_manager_stream_deadlines(jarvis_env):
    from app.inference.manager import MANAGER
    from app.providers.openai_compat import OpenAICompatProvider

    completions = _Completions(content="ready")
    provider = OpenAICompatProvider(base_url="http://127.0.0.1:8088/v1", model="qwen-test")
    provider.client = _Client(completions)
    MANAGER.provider = provider
    MANAGER.state.context_size = 16384
    MANAGER.state.server_n_ctx = 16384
    MANAGER.state.loaded = True
    chunks: list[str] = []
    async for delta in MANAGER.chat_stream(
        [ChatMessage(role="user", content="Say only the word ready")],
        settings=jarvis_env["settings"],
        max_tokens=32,
    ):
        chunks.append(delta)
    assert "".join(chunks) == "ready"
    assert completions.kwargs.get("stream") is True


@pytest.mark.asyncio
async def test_real_provider_honours_first_token_deadline(jarvis_env):
    from app.inference.manager import MANAGER
    from app.providers.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(base_url="http://127.0.0.1:8088/v1", model="qwen-test")
    provider.client = _Client(_Completions(stall=True))
    MANAGER.provider = provider
    MANAGER.state.context_size = 16384
    MANAGER.state.server_n_ctx = 16384
    MANAGER.state.loaded = True
    settings = jarvis_env["settings"]
    settings.inference.stream_first_token_base_ms = 0
    settings.inference.stream_first_token_min_ms = 30
    settings.inference.stream_first_token_max_ms = 1000
    settings.inference.stream_idle_ms = 250
    with pytest.raises(StreamStallError):
        async for _delta in MANAGER.chat_stream(
            [ChatMessage(role="user", content="hello")],
            settings=settings,
            max_tokens=16,
        ):
            pass


@pytest.mark.asyncio
async def test_managed_llama_grows_context_toward_hardware_cap(monkeypatch):
    from app.config import AppSettings
    from app.inference.manager import InferenceManager
    from app.inference.profiles import PROFILES
    from app.inference.prompt_budget import choose_context_window, prepare_inference

    monkeypatch.setattr("app.inference.ram_policy._ram_total_gb", lambda: 64.0)
    assert choose_context_window(40000, 65536, 16384) == 65536
    manager = InferenceManager()
    manager.backend = type("ManagingBackend", (), {"manages_process": True})()
    manager.state.context_size = 16384
    manager.state.server_n_ctx = 16384
    manager.state.loaded = True
    manager.state.profile = "bootstrap"
    seen: dict[str, int] = {}

    async def fake_load(settings, profile, context_size=None, force=False, **kwargs):
        del settings, profile, kwargs
        assert force is True
        seen["context_size"] = int(context_size or 0)
        manager.state.context_size = seen["context_size"]
        manager.state.server_n_ctx = seen["context_size"]
        return manager.state

    manager.load = fake_load
    prepared = await prepare_inference(
        [ChatMessage(role="user", content="y" * 40000)],
        None,
        PROFILES["bootstrap"],
        1024,
        AppSettings(),
        manager=manager,
    )
    assert seen["context_size"] >= 32768
    assert prepared.budget.active_context >= 32768
    assert prepared.budget.profile_cap == 65536
    assert prepared.budget.required_context <= prepared.budget.active_context


@pytest.mark.asyncio
async def test_context_pressure_does_not_change_the_active_model(monkeypatch, jarvis_env):
    from app.inference.context_model_select import _local_weights_ready, select_profile_for_context
    from app.inference.profiles import PROFILES
    from app.inference.prompt_budget import PromptBudget
    from app.inference.runtime_profiles import RuntimeProfile
    from app.observability import rolling_log
    from app.persona.inference_context import maybe_autoselect_runtime_for_budget

    logs = jarvis_env["tmp"] / "logs"
    monkeypatch.setattr(rolling_log, "logs_dir", lambda: logs)
    activated: list[str] = []

    async def activate(runtime, *, force=False):
        del force
        activated.append(runtime.name)

    monkeypatch.setattr("app.inference.hotswap.activate_runtime_profile", activate)
    current = RuntimeProfile(
        id="boot",
        name="bootstrap",
        label="Bootstrap",
        model="ornith",
        provider="local-llama",
        endpoint="127.0.0.1:8088",
        context_limit=16384,
        quantization="Q4",
        privacy_class="local-only",
        cost_ceiling_usd=None,
        model_profile="bootstrap",
    )
    ollama = RuntimeProfile(
        id="umi",
        name="umi-opus-9b",
        label="Umi",
        model="hf.co/TheCidSama/Qwen3.5-9b-Claude-4.8-Opus-reasoning",
        provider="ollama",
        endpoint="127.0.0.1:11434",
        context_limit=32768,
        quantization="",
        privacy_class="local-only",
        cost_ceiling_usd=None,
        model_profile="umi-opus-9b",
    )
    assert _local_weights_ready(ollama) is False
    assert select_profile_for_context(40000, [current, ollama], current) is None
    monkeypatch.setattr(
        "app.persona.inference_context.list_runtime_profiles",
        lambda: [current, ollama],
    )
    settings = jarvis_env["settings"]
    settings.inference.profile = "bootstrap"
    settings.inference.backend = "llama.cpp"
    settings.inference.host = "127.0.0.1"
    settings.inference.port = 8088
    budget = PromptBudget(
        prompt_tokens=20000,
        tool_tokens=0,
        output_reserve=1024,
        system_reserve=256,
        required_context=40000,
        active_context=16384,
        profile_cap=16384,
        pressure=2.4,
    )
    switched = await maybe_autoselect_runtime_for_budget(
        budget,
        PROFILES["bootstrap"],
        settings,
        task_id="nightly-model",
    )
    assert switched is None
    assert activated == []
    assert settings.inference.profile == "bootstrap"
    assert settings.inference.backend == "llama.cpp"
    assert settings.inference.port == 8088
    text = (logs / "rolling-log.jsonl").read_text(encoding="utf-8")
    assert "model_switch_refused" in text
    assert "umi-opus" not in settings.inference.backend


@pytest.mark.asyncio
async def test_remember_stores_repo_and_vault_and_recall_finds_it(jarvis_env, monkeypatch, tmp_path):
    from app.agent.tool_exposure import tool_names_for
    from app.agent.turn_working_set import _compose_memory_working_set
    from app.memory.obsidian_vault import bind_vault, reset_vault_store, unbind_vault
    from app.memory.owner_facts import recall_owner_facts, remember_owner_fact
    from app.memory.store import reset_context_repo_store

    monkeypatch.setattr("app.memory.store.data_dir", lambda: jarvis_env["tmp"])
    data_root = tmp_path / "vault-meta"
    vault = tmp_path / "vault"
    data_root.mkdir()
    vault.mkdir()
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_context_repo_store()
    reset_vault_store()
    bind_vault(str(vault), init_layout=True)
    try:
        prompt = "Remember that the porch code is blue"
        names = tool_names_for("mixed", prompt=prompt)
        assert "vault_memory" in names
        outcome = await remember_owner_fact(prompt, task_id="remember-1")
        assert outcome["stored"] is True
        assert outcome["repo"] is True
        note = vault / "Memory" / "owner-facts.md"
        assert note.is_file()
        assert "porch code is blue" in note.read_text(encoding="utf-8")
        recalled = await recall_owner_facts("what do you remember")
        assert "porch code is blue" in recalled
        composed = await _compose_memory_working_set("owner", "what do you remember")
        assert "porch code is blue" in composed.block
    finally:
        unbind_vault()
        reset_vault_store()
        reset_context_repo_store()


@pytest.mark.asyncio
async def test_remember_task_does_not_complete_when_nothing_was_stored(jarvis_env):
    from app.agent.loop import AgentRuntime
    from app.agent.planning import WorkingState

    loop = AgentRuntime()
    working = WorkingState(memory_stored=False)
    completed = await loop._complete(
        "no-such-task",
        [],
        "Remember that the porch code is blue",
        "",
        working,
        None,
    )
    assert completed is False


def test_internal_instructions_are_not_attributed_to_the_owner():
    from app.agent.chat_turns import visible_chat_turns
    from app.agent.compaction import serialize_messages
    from app.agent.prompts import PLAN_PROMPT

    raw = serialize_messages(
        [
            ChatMessage(role="system", content="system"),
            ChatMessage(role="user", content="Say only the word ready"),
            ChatMessage(role="user", content=PLAN_PROMPT, audience="internal"),
            ChatMessage(role="assistant", content="ready"),
        ]
    )
    turns = visible_chat_turns("Say only the word ready", raw, "ready")
    assert [item["content"] for item in turns] == ["Say only the word ready", "ready"]
    assert all(item["role"] != "user" or "END STATE" not in item["content"] for item in turns)


def test_trivial_and_reply_only_requests_stay_in_chat():
    from app.agent.instruction_gate import tool_write_denied
    from app.agent.planning import DIRECT_REPLY, MANAGED_TASK, route_request

    assert route_request("Say only the word ready").kind == DIRECT_REPLY
    coding = "Return only the code for a ping script. Do not write a file."
    assert route_request(coding).kind == DIRECT_REPLY
    assert route_request("Install the update and verify it works").kind == MANAGED_TASK
    assert route_request("open steam").kind == MANAGED_TASK
    denied = tool_write_denied(
        "filesystem",
        {"action": "write", "path": "Desktop/Get-AnzuPing.ps1", "content": "ping"},
        coding,
    )
    assert denied is not None
    assert denied.startswith("ERROR:")


def test_internal_plan_turn_does_not_drop_the_memory_tool():
    """Tool grants follow the owner's request, not the internal plan instruction."""
    from app.agent.chat_turns import internal_user_message
    from app.agent.loop import _latest_owner_text, _pin_granted_schemas, _tool_grant_prompt
    from app.agent.planning import WorkingState
    from app.agent.prompts import PLAN_PROMPT
    from app.agent.tool_exposure import schemas_for, tool_names_for
    from app.agent.turn_tools import select_turn_schemas

    owner = "Remember that the porch code is blue"
    messages = [
        ChatMessage(role="user", content=owner),
        internal_user_message(PLAN_PROMPT),
    ]
    chosen = _latest_owner_text(messages, owner)
    assert "porch code" in chosen
    assert "END STATE" not in chosen
    grant_prompt = _tool_grant_prompt(messages, owner)
    assert "porch code" in grant_prompt
    assert "END STATE" in grant_prompt
    names = tool_names_for("mixed", prompt=grant_prompt, needs_tools=True)
    assert "vault_memory" in names
    schemas = schemas_for("mixed", prompt=grant_prompt, needs_tools=True)
    granted = {item.get("function", {}).get("name") for item in schemas}
    assert "vault_memory" in granted
    trimmed = select_turn_schemas(schemas, model_family="9b-abliterated", prompt="unrelated", limit=1)
    pinned = _pin_granted_schemas(trimmed, WorkingState(), grant_prompt)
    assert "vault_memory" in {item.get("function", {}).get("name") for item in pinned or []}
    # Same intersection the task API uses: a stored grant survives when the prompt is the owner's.
    allowed = set(tool_names_for("mixed", security_role="", prompt=owner))
    exposed = [item for item in ("filesystem", "python", "mcp_call", "vault_memory") if item in allowed]
    assert "vault_memory" in exposed


def test_installer_allowlist_skips_scratch_folders_and_sidecar_collects_kokoro():
    iss = (ROOT / "installer" / "windows" / "Jarvis.iss").read_text(encoding="utf-8")
    assert 'Source: "..\\..\\*";' not in iss
    assert 'Source: "..\\..\\backend\\*"' in iss
    assert 'Source: "..\\..\\frontend\\*"' in iss
    assert "_*\\*" in iss
    assert "tools\\license_manager" in iss
    assert "Logo_black.png" in iss
    assert "Releases\\*" in iss
    sidecar = (ROOT / "scripts" / "build-backend-sidecar.ps1").read_text(encoding="utf-8")
    assert "--hidden-import kokoro" in sidecar
    assert "--collect-all kokoro" in sidecar
    assert "--hidden-import soundfile" in sidecar
    assert "--verify-frozen-imports" in sidecar
    entry = (ROOT / "backend" / "jarvis_sidecar.py").read_text(encoding="utf-8")
    assert "--verify-frozen-imports" in entry
    assert "kokoro" in entry
