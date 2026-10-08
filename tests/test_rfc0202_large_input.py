from types import SimpleNamespace
import json

import pytest

from app.inference.context_window import extract_loaded_n_ctx
from app.inference.large_input import reduce_user_text, retain_input
from app.inference.lmstudio_context import admitted
from app.inference.profiles import PROFILES
from app.providers.base import ChatMessage, ChatResult


def test_quick_profile_16k():
    assert PROFILES['fast'].context_size == 16384


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
                       status='idle', queued=0, parallel=1)
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
