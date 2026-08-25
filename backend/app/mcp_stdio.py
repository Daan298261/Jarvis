from __future__ import annotations

"""Stdio MCP entrypoint: PYTHONPATH=backend python3 -m app.mcp_stdio"""

import asyncio
import json
import sys

from .mcp_server import JarvisMcpServer


async def _run() -> None:
    server = JarvisMcpServer()
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            message = json.loads(stripped)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
            continue
        response = await server.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
