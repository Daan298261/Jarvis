"""Run `python -m app.acp_stdio` for a local newline-delimited JSON-RPC ACP adapter."""
from __future__ import annotations

import asyncio
import json
import sys

from .agent.acp_adapter import ACPAgentAdapter, AcpProtocolError
from .config import load_settings
from .db.session import init_db


async def serve_stdio() -> None:
    await init_db()
    adapter = ACPAgentAdapter(load_settings().acp_adapter)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = await adapter.handle(request)
            response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except (json.JSONDecodeError, AcpProtocolError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": str(exc)}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    asyncio.run(serve_stdio())
