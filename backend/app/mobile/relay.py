"""Outbound relay agent: carries the gateway's TLS bytes without terminating TLS."""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.client import connect

log = logging.getLogger(__name__)


async def tunnel(base_url: str, credential: str, tunnel_id: str, local_port: int):
    async with connect(base_url + "/v1/tunnel/" + tunnel_id, additional_headers={"Authorization": "Bearer " + credential}, max_size=131072) as ws:
        reader, writer = await asyncio.open_connection("127.0.0.1", local_port)
        async def send():
            while chunk := await reader.read(65536):
                await ws.send(chunk)
        async def receive():
            async for chunk in ws:
                if not isinstance(chunk, bytes):
                    raise ValueError("Unexpected relay frame")
                writer.write(chunk)
                await writer.drain()
        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            await writer.wait_closed()


async def run(url: str, credential: str, local_port: int = 4781):
    if not url.startswith("https://"):
        raise ValueError("Relay control requires HTTPS")
    base = "wss://" + url[8:].rstrip("/")
    backoff = 1
    while True:
        active = set()
        try:
            async with connect(base + "/v1/control", additional_headers={"Authorization": "Bearer " + credential}, max_size=4096) as ws:
                backoff = 1
                async for frame in ws:
                    message = json.loads(frame)
                    task = asyncio.create_task(tunnel(base, credential, message["tunnel"], local_port))
                    active.add(task)
                    def done(completed):
                        active.discard(completed)
                        if not completed.cancelled():
                            completed.exception()
                    task.add_done_callback(done)
        except Exception:
            log.warning("Mobile relay disconnected; reconnecting")
        finally:
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
        await asyncio.sleep(backoff)
        backoff = min(60, backoff * 2)
