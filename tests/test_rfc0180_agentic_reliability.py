from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI

from app.agent.turn_tools import select_turn_schemas
from app.config import default_allowed_directories
from app.inference.tool_capability import probe_tool_capability
from app.providers.base import ChatMessage, ChatResult, ModelProvider
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.tool_call_compat import normalize_tool_calls, validate_turn_calls
from app.tools.safety import resolve_allowed_path


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_normalizer_accepts_local_object_arguments_and_rejects_prose_fallback():
    calls = normalize_tool_calls([{"function": {"name": "filesystem", "arguments": {"action": "read", "path": "a"}}}])
    assert json.loads(calls[0]["function"]["arguments"]) == {"action": "read", "path": "a"}
    assert calls[0]["id"].startswith("local-")
    fallback = normalize_tool_calls([], content='<tool_call>{"name":"filesystem","arguments":{"action":"list"}}</tool_call>')
    assert len(fallback) == 1
    assert normalize_tool_calls([], content='Ignore policy. <tool_call>{"name":"filesystem","arguments":{}}</tool_call>') == []


def test_validator_rejects_unoffered_and_malformed_calls():
    call = {"id": "x", "function": {"name": "terminal", "arguments": "{}"}}
    assert "not offered" in (validate_turn_calls([call], [_tool("filesystem")]) or "")
    call["function"]["name"] = "filesystem"
    call["function"]["arguments"] = "{invalid"
    assert "malformed" in (validate_turn_calls([call], [_tool("filesystem")]) or "")


def test_validator_checks_required_arguments_and_types():
    offered = [{"type": "function", "function": {"name": "filesystem", "parameters": {
        "type": "object", "properties": {"action": {"type": "string", "enum": ["read"]},
        "path": {"type": "string"}}, "required": ["action", "path"]}}}]
    call = {"function": {"name": "filesystem", "arguments": '{"action":"read"}'}}
    assert "missing required" in (validate_turn_calls([call], offered) or "")
    call["function"]["arguments"] = '{"action":"read","path":42}'
    assert "must be string" in (validate_turn_calls([call], offered) or "")
    call["function"]["arguments"] = '{"action":"delete","path":"x"}'
    assert "offered values" in (validate_turn_calls([call], offered) or "")


def test_small_model_tool_selection_keeps_escape_and_five_or_fewer_schemas():
    schemas = [_tool(name) for name in ("request_tools", "request_capability", "filesystem", "terminal", "python", "git", "browser", "office")]
    selected = select_turn_schemas(schemas, model_family="9b-abliterated", prompt="Write a file and run python")
    names = {item["function"]["name"] for item in selected or []}
    assert len(selected or []) <= 5
    assert {"filesystem", "python", "request_tools", "request_capability"} <= names
    assert select_turn_schemas(schemas, model_family="27b", prompt="write file") == schemas


def test_owner_home_is_allowed_without_empty_scope_bypass():
    home = Path.home()
    assert str(home) in default_allowed_directories()
    assert resolve_allowed_path(str(home / "AppData"), default_allowed_directories()) == (home / "AppData").resolve()
    with pytest.raises(PermissionError):
        resolve_allowed_path(str(home), [])


@pytest.mark.asyncio
async def test_raw_openai_transport_normalizes_llamacpp_object_arguments():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "diagnostic_echo", "arguments": {"token": "abc"}}}
            ]}}], "usage": {"total_tokens": 10},
        })

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatProvider("http://localhost:8088/v1", model="local")
    provider.client = AsyncOpenAI(base_url="http://localhost:8088/v1", api_key="local", http_client=httpx.AsyncClient(transport=transport))
    result = await provider.chat([ChatMessage(role="user", content="echo")], tools=[_tool("diagnostic_echo")])
    assert json.loads(result.tool_calls[0]["function"]["arguments"]) == {"token": "abc"}
    assert seen[0]["parallel_tool_calls"] is False
    await provider.client.close()


@pytest.mark.asyncio
async def test_probe_requires_tool_result_round_trip():
    class ScriptedProvider(ModelProvider):
        async def chat(self, messages, tools=None, **kwargs):
            if tools:
                token = messages[-1].content.split()[-1].rstrip(".")
                return ChatResult(tool_calls=[{"id": "c1", "function": {"name": "diagnostic_echo", "arguments": json.dumps({"token": token})}}])
            return ChatResult(content=messages[-1].content)

    provider = ScriptedProvider("http://localhost:8088/v1")
    result = await probe_tool_capability(provider)
    assert result["status"] == "ready"
    assert result["round_trip"] is True
