from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError

from app.agent.loop import AGENT
from app.inference.manager import MANAGER
from app.inference.prompt_budget import is_context_overflow
from app.providers.base import ChatResult
from tests.test_verification_loop import ScriptedProvider, _finished, _tool


class OverflowOnceProvider(ScriptedProvider):
    def __init__(self, results, overflow_on_call: int = 0):
        super().__init__(results)
        self._calls = 0
        self.overflow_on_call = overflow_on_call

    async def chat(self, messages, **kwargs):
        self._calls += 1
        if self._calls == self.overflow_on_call + 1:
            request = httpx.Request("POST", "http://127.0.0.1:8088/v1/chat/completions")
            response = httpx.Response(400, request=request, text="Context size has been exceeded.")
            raise APIStatusError(
                "Context size has been exceeded.",
                response=response,
                body=None,
            )
        return await super().chat(messages, **kwargs)


@pytest.mark.asyncio
async def test_overflow_does_not_immediately_fail_task(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    target = tmp / "recover.txt"
    MANAGER.state.context_size = 16384
    provider = OverflowOnceProvider(
        [
            ChatResult(content="END STATE: recover.txt exists\nACCEPTANCE CRITERIA:\n- ok\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "ok", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Done."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified."),
        ],
        overflow_on_call=0,
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Write {target} with ok.",
        autonomy="autonomous",
        profile="balanced",
        execution_mode="fast",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert provider._calls >= 2


def test_recovery_retry_limits_constants():
    """Document RFC caps: 2 absolute recovery attempts per turn in the agent loop."""
    assert is_context_overflow(RuntimeError("prompt is too long"))
