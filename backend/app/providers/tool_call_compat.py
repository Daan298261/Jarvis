"""Normalize local OpenAI-compatible tool calls before they reach ANZU's policy loop."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .completion_text import strip_think_blocks

_TOOL_BLOCKS = re.compile(r"\s*<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
MAX_ARGUMENT_CHARS = 32768


def _qwen_blocks(content: str) -> list[dict[str, Any]]:
    """Accept only complete canonical Qwen JSON tool blocks, never prose with embedded commands."""
    text = strip_think_blocks(content or "")
    if not text or "<tool_call>" not in text:
        return []
    pos = 0
    calls: list[dict[str, Any]] = []
    for match in _TOOL_BLOCKS.finditer(text):
        if text[pos:match.start()].strip():
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        calls.append(payload)
        pos = match.end()
    return calls if calls and not text[pos:].strip() else []


def normalize_tool_calls(calls: Any, *, content: str = "") -> list[dict[str, Any]]:
    source = calls if isinstance(calls, list) and calls else _qwen_blocks(content)
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(source):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments", {})
        if isinstance(arguments, dict):
            encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(arguments, str):
            encoded = arguments
        else:
            encoded = ""
        if len(encoded) > MAX_ARGUMENT_CHARS:
            encoded = ""
        call_id = str(raw.get("id") or "").strip()
        if not call_id:
            digest = hashlib.sha256(f"{index}:{name}:{encoded}".encode()).hexdigest()[:16]
            call_id = f"local-{digest}"
        result.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": encoded}})
    return result


def validate_turn_calls(calls: list[dict[str, Any]], offered: list[dict[str, Any]] | None) -> str | None:
    schemas = {str(item.get("function", {}).get("name") or ""): item.get("function", {}).get("parameters", {})
               for item in (offered or [])}
    names = set(schemas)
    if len(calls) > 4:
        return "Too many tool calls in one turn; request one action at a time."
    for call in calls:
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        if name not in names:
            return f"Tool {name or '(unnamed)'} was not offered on this turn. Use an offered tool or request a capability."
        raw = function.get("arguments")
        if not isinstance(raw, str) or not raw or len(raw) > MAX_ARGUMENT_CHARS:
            return f"Tool {name} has invalid or oversized arguments. Return a JSON object."
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return f"Tool {name} arguments are malformed JSON. Return a JSON object."
        if not isinstance(parsed, dict):
            return f"Tool {name} arguments must be a JSON object."
        schema = schemas[name]
        if isinstance(schema, dict):
            required = schema.get("required", [])
            if isinstance(required, list):
                missing = [key for key in required if key not in parsed]
                if missing:
                    return f"Tool {name} is missing required arguments: {', '.join(map(str, missing))}."
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                for key, value in parsed.items():
                    rule = properties.get(key)
                    if not isinstance(rule, dict):
                        continue
                    expected = rule.get("type")
                    valid = {"string": lambda v: isinstance(v, str),
                             "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                             "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                             "boolean": lambda v: isinstance(v, bool),
                             "object": lambda v: isinstance(v, dict),
                             "array": lambda v: isinstance(v, list)}
                    if isinstance(expected, str) and expected in valid and not valid[expected](value):
                        return f"Tool {name} argument {key} must be {expected}."
                    choices = rule.get("enum")
                    if isinstance(choices, list) and value not in choices:
                        return f"Tool {name} argument {key} must be one of the offered values."
    return None
