from types import SimpleNamespace
import json
import asyncio
import threading

import pytest

from app.config import SocialCommentarySettings
from app.inference.context_window import extract_loaded_n_ctx
from app.inference.large_input import acknowledgment_line, reduce_user_text, retain_input
from app.inference.large_input import sections
from app.inference.lmstudio_context import (
    LocalContextRestoreError,
    admitted,
    instance_load_args,
)
from app.inference.manager import InferenceManager
from app.inference.profiles import PROFILES
from app.inference.request_lease import RequestLease
from app.providers.base import ChatMessage, ChatResult


def test_quick_profile_16k():
    assert PROFILES['fast'].context_size == 16384


def test_unicode_sections_are_lossless_and_byte_bounded():
    from app.inference.prompt_budget import estimate_text_tokens
    from app.inference.large_input import text_cost
    text = '🦅世界abc' * 2000
    parts = sections(text, 1365)
    assert ''.join(parts) == text
    assert all(len(part.encode('utf-8')) <= 1365 for part in parts)
    assert estimate_text_tokens(text) >= 10000
    assert text_cost(text) >= 2 * estimate_text_tokens(text)


def test_live_config_and_unloaded_catalog():
    assert extract_loaded_n_ctx({'models': [
        {'max_context_length': 262144, 'loaded_instances': []},
        {'max_context_length': 262144, 'loaded_instances': [{'config': {'context_length': 65536}}]},
    ]}) == 65536
    assert extract_loaded_n_ctx({'max_context_length': 262144, 'loaded_instances': []}) is None


def test_headroom_64k_admitted_262k_rejected():
    resources = dict(gpu_total_gib=15.92, other_gpu_gib=0.1, available_ram_gib=31)
    assert admitted(12.57, 12.57, **resources)
    assert not admitted(24.41, 24.41, **resources)
    assert not admitted(12.57, 12.57, **(resources | {'available_ram_gib': 15}))


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_load', [False, True])
async def test_local_resize_verified_or_rolled_back(monkeypatch, jarvis_env, fail_load):
    import app.inference.lmstudio_context as module
    settings = jarvis_env['settings']
    settings.inference.host, settings.inference.port = '127.0.0.1', 1234
    monkeypatch.setattr(module.shutil, 'which', lambda name: 'lms-test')
    monkeypatch.setattr(module.psutil, 'virtual_memory', lambda: SimpleNamespace(available=32 * 1024**3))
    size = 4096
    loads = []
    def run(argv, **kwargs):
        nonlocal size
        if argv[0] == 'nvidia-smi':
            return SimpleNamespace(returncode=0, stdout='16303,8192', stderr='')
        if argv[1] == 'ps':
            row = dict(identifier='owner', modelKey='qwen', contextLength=size, maxContextLength=262144,
                       status='idle', queued=0, parallel=1, gpu=0.55, ttl=90)
            return SimpleNamespace(returncode=0, stdout=json.dumps([row]), stderr='')
        if '--estimate-only' in argv:
            target = int(argv[argv.index('--context-length') + 1])
            estimate = 8 if target == 4096 else 12.57
            return SimpleNamespace(returncode=0, stdout=f'Estimated GPU Memory: {estimate} GiB\nEstimated Total Memory: {estimate} GiB', stderr='')
        if argv[1] == 'load':
            target = int(argv[argv.index('--context-length') + 1])
            loads.append(target)
            if fail_load and target == 65536:
                return SimpleNamespace(returncode=1, stdout='', stderr='load failed')
            size = target
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(module.subprocess, 'run', run)
    result = await module.grow_local_instance(settings, 65536, 'owner')
    if fail_load:
        assert result is None and size == 4096 and loads == [65536, 4096]
    else:
        assert result == size == 65536 and loads == [65536]


@pytest.mark.asyncio
async def test_remote_resize_never_invokes_local_cli(monkeypatch, jarvis_env):
    import app.inference.lmstudio_context as module
    settings = jarvis_env['settings']
    settings.inference.host = '192.0.2.5'
    monkeypatch.setattr(module.shutil, 'which', lambda name: pytest.fail('must not run CLI'))
    assert await module.grow_local_instance(settings, 65536, 'owner') is None


@pytest.mark.asyncio
async def test_voice_probe_cannot_block_event_loop(jarvis_env, monkeypatch):
    from app.systems import self_check
    entered, release = threading.Event(), threading.Event()
    async def model(*args):
        return {'loaded': True, 'active_model': 'fixture'}
    def slow_probe():
        entered.set()
        release.wait(2)
        return {'kokoro': True, 'kokoro_weights': True}
    monkeypatch.setattr(self_check.MANAGER, 'snapshot', model)
    monkeypatch.setattr(self_check, 'engine_availability', slow_probe)
    monkeypatch.setattr(self_check, 'voice_status', lambda: {'stt_ready': True})
    pending = asyncio.create_task(self_check.run_self_check())
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait), .5)
        # This heartbeat runs while the deliberately stalled synchronous probe is pending.
        await asyncio.wait_for(asyncio.sleep(.01), .1)
        assert not pending.done()
    finally:
        release.set()
        await pending


def test_voicestudio_probe_has_shared_deadline_and_negative_cache(monkeypatch):
    from app.tts import voicestudio_adapter as module
    module._probe_cache.clear()
    monkeypatch.delenv('JARVIS_DISABLE_VOICESTUDIO', raising=False)
    monkeypatch.setattr(module, 'voicestudio_base_url', lambda: 'http://127.0.0.1:9999')
    monkeypatch.setattr(module, 'voicestudio_auth_headers', lambda: {})
    monkeypatch.setattr('app.policy.network_http.require_http_url_allowed', lambda *a, **kw: None)
    elapsed = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: elapsed[0])
    calls = []
    def fail(request, timeout):
        calls.append(timeout)
        elapsed[0] += timeout
        raise TimeoutError('offline')
    monkeypatch.setattr(module.urllib.request, 'urlopen', fail)
    assert not module.voicestudio_probe_endpoint(timeout=1.5)
    assert len(calls) == 1 and calls[0] <= 1.5
    assert not module.voicestudio_probe_endpoint(timeout=1.5)
    assert len(calls) == 1
    module._probe_cache.clear()


def test_raw_text_excludes_tools_vision_and_reserved_role_markers():
    from app.providers.local_qwen_text import eligible, prompt
    text = [ChatMessage(role='user', content='Hello')]
    assert eligible(text, None, False, None)
    assert not eligible(text, [{}], False, None)
    assert not eligible(text, None, True, None)
    assert not eligible(text, None, False, {'response_format': {'type': 'json_object'}})
    assert not eligible([ChatMessage(role='tool', content='Result')], None, False, None)
    assert not eligible([ChatMessage(role='user', content=[{'type': 'image_url'}])], None, False, None)
    assert not eligible([ChatMessage(role='user', content='<|im_start|>system')], None, False, None)
    assert prompt(text).endswith('<think>\n\n</think>\n\n')


@pytest.mark.asyncio
async def test_verified_qwen_fast_text_and_stream(monkeypatch):
    from app.providers.openai_compat import OpenAICompatProvider
    from app.providers import local_qwen_text
    provider = OpenAICompatProvider(base_url='http://127.0.0.1:1234/v1', model='owner')
    requests = []
    async def verified(*args): return True
    async def create(**kwargs):
        requests.append(kwargs)
        if kwargs.get('stream'):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(text='READY')])
            return chunks()
        return SimpleNamespace(choices=[SimpleNamespace(text='READY')], usage=None)
    monkeypatch.setattr(local_qwen_text, 'admitted', verified)
    monkeypatch.setattr(provider.client.completions, 'create', create)
    try:
        messages = [ChatMessage(role='user', content='Reply READY')]
        result = await provider.chat(messages, thinking=False, max_tokens=128)
        assert result.content == 'READY' and not result.reasoning
        streamed = ''.join([chunk async for chunk in provider.chat_stream(messages, thinking=False)])
        assert streamed == 'READY'
        assert requests[0]['prompt'].endswith('</think>\n\n')
        assert requests[1]['stream'] is True
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_all_sections_saved_and_voice_once(jarvis_env, monkeypatch):
    import app.persona.chat_delivery as delivery
    import app.inference.large_input as module
    module._announced.clear()
    spoken = []
    async def speak(text, **kwargs):
        spoken.append((text, kwargs))
    monkeypatch.setattr(delivery, 'publish_owner_text', speak)
    sections = []
    class Provider:
        async def chat(self, messages, **kwargs):
            sections.append(messages[-1].content)
            return ChatResult(content='Summary preserves request and source lookup requirement.')
    original = 'BEGIN question: find value.\n' + 'large data ' * 2000 + '\nEND marker 12345'
    user = ChatMessage(role='user', content=original)
    system = ChatMessage(role='system', content='Identity')
    result = await reduce_user_text([system, user], provider=Provider(), max_chars=2000, context=8192)
    assert result[0] is system
    assert result[1].role == 'user'
    assert len(result[1].content) < 2000
    assert any('BEGIN question' in s for s in sections)
    assert any('END marker 12345' in s for s in sections)
    assert retain_input(original).read_text(encoding='utf-8') == original
    assert len(spoken) == 1 and spoken[0][1]['speak'] is True
    await module.acknowledge(original)
    assert len(spoken) == 1


@pytest.mark.asyncio
async def test_failure_never_returns_partial_summary(jarvis_env, monkeypatch):
    import app.persona.chat_delivery as delivery
    async def speak(*args, **kwargs): pass
    monkeypatch.setattr(delivery, 'publish_owner_text', speak)
    class Provider:
        calls = 0
        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('provider disconnected')
            return ChatResult(content='first section')
    original = 'unique failure test ' * 1000
    message = ChatMessage(role='user', content=original)
    with pytest.raises(RuntimeError, match='disconnected'):
        await reduce_user_text([message], provider=Provider(), max_chars=1800, context=4096)
    assert message.content == original
    assert retain_input(original).read_text(encoding='utf-8') == original


@pytest.mark.asyncio
async def test_non_reducing_provider_fails(jarvis_env, monkeypatch):
    import app.persona.chat_delivery as delivery
    async def speak(*args, **kwargs): pass
    monkeypatch.setattr(delivery, 'publish_owner_text', speak)
    class Provider:
        async def chat(self, messages, **kwargs):
            return ChatResult(content='x' * 5000)
    with pytest.raises(ValueError, match='did not reduce'):
        await reduce_user_text([ChatMessage(role='user', content='x' * 10000)],
                               provider=Provider(), max_chars=1800, context=4096)


def test_acknowledgment_default_has_no_honorific():
    line = acknowledgment_line(SocialCommentarySettings())
    assert line == "That's a lot of text. I'll divide it into sections so I can read it properly."
    assert "sir" not in line.lower()


def test_acknowledgment_honors_configured_address_style():
    sir = acknowledgment_line(SocialCommentarySettings(address_style="sir_maam"))
    assert sir == "That's a lot of text, sir. I'll divide it into sections so I can read it properly."
    named = acknowledgment_line(
        SocialCommentarySettings(address_style="configured", configured_address_name="Alex")
    )
    assert named == "That's a lot of text, Alex. I'll divide it into sections so I can read it properly."
    first = acknowledgment_line(
        SocialCommentarySettings(address_style="first_name", configured_address_name="Dana")
    )
    assert "Dana" in first and "sir" not in first.lower()


def test_instance_load_args_use_original_gpu_not_max():
    args = [str(part) for part in instance_load_args(
        {"gpu": {"ratio": 0.42}, "parallel": 2, "ttl": 60, "config": {"flashAttention": True}},
        key="qwen",
        identifier="owner",
        context_length=4096,
    )]
    assert args[args.index("--gpu") + 1] == "0.42"
    assert "max" not in args
    assert args[args.index("--parallel") + 1] == "2"
    assert args[args.index("--ttl") + 1] == "60"
    assert "--flash-attention" in args


def _patch_lms_cli(monkeypatch, module, *, row_factory, on_load=None):
    monkeypatch.setattr(module.shutil, "which", lambda name: "lms-test")
    monkeypatch.setattr(module.psutil, "virtual_memory", lambda: SimpleNamespace(available=32 * 1024**3))
    commands = []

    def run(argv, **kwargs):
        commands.append(list(argv))
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(returncode=0, stdout="16303,8192", stderr="")
        if argv[1] == "ps":
            return SimpleNamespace(returncode=0, stdout=json.dumps([row_factory()]), stderr="")
        if "--estimate-only" in argv:
            target = int(argv[argv.index("--context-length") + 1])
            estimate = 8 if target == 4096 else 12.57
            return SimpleNamespace(
                returncode=0,
                stdout=f"Estimated GPU Memory: {estimate} GiB\nEstimated Total Memory: {estimate} GiB",
                stderr="",
            )
        if argv[1] == "load" and on_load is not None:
            return on_load(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    return commands


@pytest.mark.asyncio
async def test_busy_recheck_does_not_unload(monkeypatch, jarvis_env):
    import app.inference.lmstudio_context as module
    settings = jarvis_env["settings"]
    settings.inference.host, settings.inference.port = "127.0.0.1", 1234
    ps_calls = {"n": 0}

    def row_factory():
        ps_calls["n"] += 1
        busy = ps_calls["n"] > 1
        return dict(
            identifier="owner", modelKey="qwen", contextLength=4096, maxContextLength=262144,
            status="busy" if busy else "idle", queued=1 if busy else 0, parallel=1, gpu=0.55,
        )

    commands = _patch_lms_cli(monkeypatch, module, row_factory=row_factory)
    assert await module.grow_local_instance(settings, 65536, "owner") is None
    assert not any(cmd[1] == "unload" for cmd in commands if len(cmd) > 1)


@pytest.mark.asyncio
async def test_reload_refused_while_request_lease_held(monkeypatch, jarvis_env):
    import app.inference.lmstudio_context as module
    settings = jarvis_env["settings"]
    settings.inference.host, settings.inference.port = "127.0.0.1", 1234
    size = {"n": 4096}

    def row_factory():
        return dict(
            identifier="owner", modelKey="qwen", contextLength=size["n"], maxContextLength=262144,
            status="idle", queued=0, parallel=1, gpu=0.55,
        )

    def on_load(argv):
        size["n"] = int(argv[argv.index("--context-length") + 1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    commands = _patch_lms_cli(monkeypatch, module, row_factory=row_factory, on_load=on_load)
    lease = RequestLease()
    async with lease.shared():
        assert await module.grow_local_instance(settings, 65536, "owner", lease=lease) is None
    assert not any(cmd[1] == "unload" for cmd in commands if len(cmd) > 1)
    assert size["n"] == 4096


@pytest.mark.asyncio
async def test_mid_turn_apply_context_never_reloads(monkeypatch, jarvis_env):
    called = []

    async def fake_grow(*args, **kwargs):
        called.append((args, kwargs))
        return 65536

    monkeypatch.setattr("app.inference.lmstudio_context.grow_local_instance", fake_grow)
    mgr = InferenceManager()
    mgr.state.backend = "lmstudio"
    mgr.state.server_n_ctx = 4096
    mgr.state.context_size = 4096
    mgr.provider = SimpleNamespace(model="owner")
    settings = jarvis_env["settings"]
    assert await mgr.apply_context(settings, 65536, allow_shrink=False) == 4096
    assert called == []
    assert await mgr.apply_context(settings, 65536, allow_shrink=False, allow_reload=True) == 65536
    assert len(called) == 1


@pytest.mark.asyncio
async def test_prepare_inference_never_reloads_local_instance(monkeypatch, jarvis_env):
    from app.inference.prompt_budget import ModelCapacityExceeded, prepare_inference

    called = []

    async def fake_grow(*args, **kwargs):
        called.append(1)
        return 65536

    monkeypatch.setattr("app.inference.lmstudio_context.grow_local_instance", fake_grow)
    mgr = jarvis_env["manager"]
    mgr.state.backend = "lmstudio"
    mgr.state.context_size = 4096
    mgr.state.server_n_ctx = 4096
    mgr.provider = None
    messages = [ChatMessage(role="user", content="y" * 24000)]
    try:
        await prepare_inference(messages, None, PROFILES["balanced"], 1024, jarvis_env["settings"], manager=mgr)
    except ModelCapacityExceeded:
        pass
    finally:
        mgr.state.backend = "llama.cpp"
    assert called == []


@pytest.mark.asyncio
async def test_prepare_inference_does_not_speak_when_expansion_fits(jarvis_env, monkeypatch):
    from app.inference.prompt_budget import calculate_prompt_budget, estimate_text_tokens, prepare_inference
    import app.persona.chat_delivery as delivery

    spoken = []

    async def speak(text, **kwargs):
        spoken.append(text)

    monkeypatch.setattr(delivery, "publish_owner_text", speak)
    mgr = jarvis_env["manager"]
    mgr.state.context_size = 16384
    mgr.state.server_n_ctx = 32768
    mgr.state.backend = "llama.cpp"
    mgr.backend = None
    user = ChatMessage(role="user", content="y" * 24000)
    messages = [ChatMessage(role="system", content="s"), user]
    budget = calculate_prompt_budget(
        messages, None, profile=PROFILES["balanced"], max_tokens=1024, active_context=16384
    )
    assert budget.pressure >= 0.70
    assert estimate_text_tokens(user.content) > 8192
    prepared = await prepare_inference(
        messages, None, PROFILES["balanced"], 1024, jarvis_env["settings"], manager=mgr
    )
    assert prepared.budget.pressure < 0.85
    assert spoken == []


@pytest.mark.asyncio
async def test_acknowledgment_only_after_compaction_and_section_limit(jarvis_env, monkeypatch):
    import app.inference.large_input as module
    import app.persona.chat_delivery as delivery

    module._announced.clear()
    spoken = []

    async def speak(text, **kwargs):
        spoken.append(text)

    monkeypatch.setattr(delivery, "publish_owner_text", speak)

    class Forbidden:
        async def chat(self, messages, **kwargs):
            raise AssertionError("provider must not run when sectioning is rejected")

    with pytest.raises(ValueError, match="256 sections"):
        await reduce_user_text(
            [ChatMessage(role="user", content="x" * (257 * 1024))],
            provider=Forbidden(),
            max_chars=2000,
            context=3072,
        )
    assert spoken == []

    class Provider:
        async def chat(self, messages, **kwargs):
            return ChatResult(content="Summary preserves request and source lookup requirement.")

    result = await reduce_user_text(
        [ChatMessage(role="user", content="BEGIN question: find value.\n" + "large data " * 2000)],
        provider=Provider(),
        max_chars=2000,
        context=8192,
    )
    assert result[0].role == "user"
    assert spoken == [acknowledgment_line(SocialCommentarySettings())]


@pytest.mark.asyncio
async def test_failed_restore_raises_and_uses_original_settings(monkeypatch, jarvis_env):
    import app.inference.lmstudio_context as module

    settings = jarvis_env["settings"]
    settings.inference.host, settings.inference.port = "127.0.0.1", 1234
    size = {"n": 4096}
    events = []
    monkeypatch.setattr(module, "record_event", lambda kind, **fields: events.append((kind, fields)))

    def row_factory():
        return dict(
            identifier="owner", modelKey="qwen", contextLength=size["n"], maxContextLength=262144,
            status="idle", queued=0, parallel=2, gpu=0.55, ttl=90,
        )

    def on_load(argv):
        target = int(argv[argv.index("--context-length") + 1])
        if target != 4096:
            return SimpleNamespace(returncode=1, stdout="", stderr="grow load failed")
        return SimpleNamespace(returncode=1, stdout="", stderr="restore load failed")

    commands = _patch_lms_cli(monkeypatch, module, row_factory=row_factory, on_load=on_load)
    mgr = InferenceManager()
    mgr.state.loaded = True
    mgr.state.backend = "lmstudio"
    mgr.state.server_n_ctx = 4096
    mgr.state.context_size = 4096
    mgr.provider = SimpleNamespace(model="owner")
    with pytest.raises(LocalContextRestoreError, match="could not be restored"):
        await mgr.apply_context(settings, 65536, allow_reload=True)
    assert mgr.state.loaded is False
    assert mgr.provider is None
    assert mgr.state.last_error
    mutation_loads = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "load" and "--estimate-only" not in cmd]
    assert mutation_loads, commands
    restore = mutation_loads[-1]
    assert restore[restore.index("--gpu") + 1] == "0.55"
    assert restore[restore.index("--context-length") + 1] == "4096"
    assert restore[restore.index("--parallel") + 1] == "2"
    assert restore[restore.index("--ttl") + 1] == "90"
    assert "max" not in restore
    assert any(kind == "context_restore_failed" for kind, _ in events)


@pytest.mark.asyncio
async def test_chat_holds_shared_lease_against_reload(jarvis_env):
    mgr = InferenceManager()
    mgr.state.loaded = True
    mgr.state.context_size = 16384
    mgr.state.server_n_ctx = 16384
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowProvider:
        async def chat(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return ChatResult(content="ok")

    mgr.provider = SlowProvider()
    task = asyncio.create_task(mgr.chat([ChatMessage(role="user", content="hi")]))
    await asyncio.wait_for(entered.wait(), 2)
    assert mgr._request_lease.in_flight is True
    async with mgr._request_lease.exclusive() as acquired:
        assert acquired is False
    release.set()
    assert (await task).content == "ok"
    assert mgr._request_lease.in_flight is False
