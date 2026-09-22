"""Minimal newline JSON-RPC MCP server for live client tests."""

from __future__ import annotations

import json
import sys

PROTOCOL = "2024-11-05"
TOOLS = [
    {
        "name": "ping",
        "description": "Echo text so Jarvis can prove MCP call works.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


def reply(msg_id, result=None, error=None) -> None:
    payload: dict = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method")
        msg_id = message.get("id")
        if method is None or str(method).startswith("notifications/"):
            continue
        if method == "initialize":
            reply(
                msg_id,
                {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "echo", "version": "1.0.0"},
                },
            )
            continue
        if method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
            continue
        if method == "tools/call":
            params = message.get("params") or {}
            arguments = params.get("arguments") or {}
            text = str(arguments.get("text") or "")
            reply(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"pong:{text}"}],
                    "isError": False,
                },
            )
            continue
        if method == "ping":
            reply(msg_id, {})
            continue
        reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
