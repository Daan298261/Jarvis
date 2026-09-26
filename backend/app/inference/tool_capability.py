"""Live, harmless tool-call certification for the selected local model."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import asdict, dataclass
from weakref import WeakKeyDictionary

from ..providers.base import ChatMessage, ModelProvider
from ..providers.tool_call_compat import validate_turn_calls

_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "diagnostic_echo",
        "description": "Echo a diagnostic token without changing the computer.",
        "parameters": {
            "type": "object",
            "properties": {"token": {"type": "string"}},
            "required": ["token"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class ToolCapability:
    status: str = "untested"
    model: str = ""
    detail: str = "Run a tool-call probe to certify this model for agent tasks."
    round_trip: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


_results: WeakKeyDictionary[ModelProvider, ToolCapability] = WeakKeyDictionary()
_locks: WeakKeyDictionary[ModelProvider, asyncio.Lock] = WeakKeyDictionary()


def capability_status(provider: ModelProvider | None) -> dict:
    if provider is None:
        return ToolCapability(status="unavailable", detail="Load a model before probing tools.").as_dict()
    return _results.get(provider, ToolCapability(model=provider.model)).as_dict()


async def probe_tool_capability(provider: ModelProvider, *, thinking: bool = False, force: bool = False) -> dict:
    if not force and provider in _results:
        return _results[provider].as_dict()
    lock = _locks.setdefault(provider, asyncio.Lock())
    async with lock:
        if not force and provider in _results:
            return _results[provider].as_dict()
        token = secrets.token_hex(6)
        messages = [
            ChatMessage(role="system", content="For this diagnostic, call diagnostic_echo with the exact token supplied by the user. Do not answer before the tool responds."),
            ChatMessage(role="user", content=f"Call diagnostic_echo with token {token}."),
        ]
        try:
            first = await asyncio.wait_for(
                provider.chat(messages, tools=[_PROBE_TOOL], thinking=thinking, max_tokens=256), timeout=90
            )
            error = validate_turn_calls(first.tool_calls, [_PROBE_TOOL])
            if error or len(first.tool_calls) != 1:
                raise ValueError(error or "Model did not call diagnostic_echo")
            call = first.tool_calls[0]
            import json

            arguments = json.loads(call["function"]["arguments"])
            if arguments.get("token") != token:
                raise ValueError("Tool arguments did not preserve the diagnostic token")
            messages.extend([
                ChatMessage(role="assistant", content=first.content or "", tool_calls=first.tool_calls),
                ChatMessage(role="tool", name="diagnostic_echo", tool_call_id=call["id"], content=f"Echo result: {token}"),
            ])
            second = await asyncio.wait_for(provider.chat(messages, thinking=thinking, max_tokens=128), timeout=90)
            if token not in (second.content or ""):
                raise ValueError("Model did not use the tool result in its answer")
            result = ToolCapability(status="ready", model=provider.model, detail="Tool call and result round trip passed.", round_trip=True)
        except (Exception, asyncio.TimeoutError) as exc:
            result = ToolCapability(status="failed", model=provider.model, detail=f"Tool-call probe failed: {str(exc)[:240]}")
        _results[provider] = result
        return result.as_dict()
