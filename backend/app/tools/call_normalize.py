from __future__ import annotations

import re
from typing import Any

from .python_exec import normalize_python_call

_OVERFLOW = {
    "python": "code",
    "terminal": "command",
    "filesystem": "path",
    "git": "command",
    "browser": "url",
    "web_fetch": "url",
}

_COPY_HINTS = ("shutil.copy", "copytree", "shutil.copy2", "shutil.copy(")
_SRC_RE = re.compile(r"""(?:src|source)\s*=\s*[rR]?["']([^"']+)["']""", re.I)
_DST_RE = re.compile(r"""(?:dst|dest|destination)\s*=\s*[rR]?["']([^"']+)["']""", re.I)


def _allowed_actions(tool: Any) -> tuple[str, ...]:
    params = getattr(tool, "parameters", None) or {}
    action = (params.get("properties") or {}).get("action") or {}
    enum = action.get("enum")
    if isinstance(enum, list) and enum:
        return tuple(str(item) for item in enum if item)
    return ()


def salvage_action_blob(name: str, arguments: dict[str, Any], tool: Any = None) -> dict[str, Any]:
    """Split Qwen `action: \"run_code>\\n…\"` leftovers for any tool."""
    out = dict(arguments)
    if name == "python":
        return normalize_python_call(out)
    action = str(out.get("action") or "").strip()
    allowed = _allowed_actions(tool)
    if not action or (allowed and action in allowed):
        return out
    overflow_key = _OVERFLOW.get(name, "code")
    prefixes = allowed or (action.split(">", 1)[0].split("\n", 1)[0],)
    for prefix in prefixes:
        if not action.startswith(prefix) or action == prefix:
            continue
        rest = action[len(prefix) :].lstrip(" \t>")
        rest = rest.lstrip("\r\n")
        out["action"] = prefix
        if rest and overflow_key and not str(out.get(overflow_key) or "").strip():
            out[overflow_key] = rest
        return out
    return out


def extract_python_copy_pair(code: str) -> tuple[str, str] | None:
    if not code or not any(hint in code for hint in _COPY_HINTS):
        return None
    src = _SRC_RE.search(code)
    dst = _DST_RE.search(code)
    if src and dst:
        left, right = src.group(1).strip(), dst.group(1).strip()
        if left and right and left != right:
            return left, right
    return None


def prefer_native_tool(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Reroute python shutil.copy* scripts onto filesystem copy."""
    if name != "python":
        return name, arguments
    code = str(arguments.get("code") or "")
    pair = extract_python_copy_pair(code)
    if not pair:
        return name, arguments
    src, dst = pair
    return "filesystem", {"action": "copy", "path": src, "destination": dst}


def normalize_tool_call(name: str, arguments: dict[str, Any], tool: Any = None) -> tuple[str, dict[str, Any]]:
    cleaned = salvage_action_blob(name, arguments, tool)
    return prefer_native_tool(name, cleaned)
