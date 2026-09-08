"""Opaque TCP relay and FCM broker. TLS to the Jarvis gateway is never terminated here."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

CONTROLS = {}
LISTENERS = {}
PENDING = {}
ACTIVE = defaultdict(int)
SEND_LOCKS = defaultdict(asyncio.Lock)
PUSH_WINDOWS = defaultdict(deque)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def database():
    path = Path(os.environ.get("RELAY_DATA", "/data"))
    path.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path / "relay.db")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS swarms(id TEXT PRIMARY KEY, token TEXT NOT NULL, port INTEGER UNIQUE NOT NULL)")
    db.commit()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def authorized(header):
    if not header.startswith("Bearer "):
        return None
    with database() as db:
        row = db.execute("SELECT * FROM swarms WHERE token=?", (digest(header[7:]),)).fetchone()
        return dict(row) if row else None


async def serve_swarm(swarm):
    if swarm["id"] in LISTENERS:
        return

    async def connection(reader, writer):
        swarm_id = swarm["id"]
        if swarm_id not in CONTROLS or ACTIVE[swarm_id] >= 8:
            writer.close()
            return
        ACTIVE[swarm_id] += 1
        tunnel_id = secrets.token_urlsafe(32)
        connected = asyncio.Event()
        finished = asyncio.Event()
        PENDING[tunnel_id] = (swarm_id, reader, writer, connected, finished)
        try:
            async with SEND_LOCKS[swarm_id]:
                await CONTROLS[swarm_id].send_json({"tunnel": tunnel_id})
            await asyncio.wait_for(connected.wait(), 15)
            await asyncio.wait_for(finished.wait(), 3600)
        except (TimeoutError, RuntimeError, OSError):
            pass
        finally:
            PENDING.pop(tunnel_id, None)
            ACTIVE[swarm_id] -= 1
            writer.close()
            await writer.wait_closed()

    LISTENERS[swarm["id"]] = await asyncio.start_server(connection, "0.0.0.0", swarm["port"])


@asynccontextmanager
async def lifespan(app):
    with database() as db:
        swarms = [dict(row) for row in db.execute("SELECT * FROM swarms")]
    for swarm in swarms:
        await serve_swarm(swarm)
    yield
    for listener in LISTENERS.values():
        listener.close()
        await listener.wait_closed()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class Registration(BaseModel):
    registration_code: str = Field(max_length=512)


@app.post("/v1/register")
async def register(body: Registration):
    expected = os.environ.get("RELAY_REGISTRATION_CODE", "")
    if not expected or not secrets.compare_digest(expected, body.registration_code):
        raise HTTPException(401, "Invalid installation registration code")
    token = secrets.token_urlsafe(48)
    first = int(os.environ.get("RELAY_PORT_FIRST", "15000"))
    count = int(os.environ.get("RELAY_PORT_COUNT", "100"))
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        occupied = {row[0] for row in db.execute("SELECT port FROM swarms")}
        port = next((port for port in range(first, first + count) if port not in occupied), None)
        if port is None:
            raise HTTPException(503, "Relay capacity reached")
        swarm = {"id": str(uuid.uuid4()), "token": digest(token), "port": port}
        db.execute("INSERT INTO swarms VALUES(?,?,?)", (swarm["id"], swarm["token"], port))
    await serve_swarm(swarm)
    return {"id": swarm["id"], "credential": token, "endpoint": f'https://{os.environ["RELAY_HOSTNAME"]}:{port}'}


@app.websocket("/v1/control")
async def control(ws: WebSocket):
    swarm = authorized(ws.headers.get("authorization", ""))
    if not swarm:
        await ws.close(4401)
        return
    await ws.accept()
    previous = CONTROLS.get(swarm["id"])
    if previous:
        await previous.close(1000)
    CONTROLS[swarm["id"]] = ws
    try:
        while True:
            # websockets' protocol pings maintain NAT mappings without content.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if CONTROLS.get(swarm["id"]) is ws:
            CONTROLS.pop(swarm["id"], None)


@app.websocket("/v1/tunnel/{tunnel_id}")
async def tunnel(tunnel_id: str, ws: WebSocket):
    swarm = authorized(ws.headers.get("authorization", ""))
    pending = PENDING.get(tunnel_id)
    if not swarm or not pending or pending[0] != swarm["id"] or pending[3].is_set():
        await ws.close(4401)
        return
    _, reader, writer, connected, finished = pending
    await ws.accept()
    connected.set()

    async def to_agent():
        total = 0
        while chunk := await reader.read(65536):
            total += len(chunk)
            if total > 512 * 1024 * 1024:
                break
            await ws.send_bytes(chunk)

    async def to_phone():
        total = 0
        while True:
            chunk = await ws.receive_bytes()
            total += len(chunk)
            if total > 512 * 1024 * 1024:
                break
            writer.write(chunk)
            await writer.drain()

    tasks = [asyncio.create_task(to_agent()), asyncio.create_task(to_phone())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        finished.set()
        try:
            await ws.close()
        except RuntimeError:
            pass


class Push(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    data: dict[str, str]


@app.post("/v1/push")
async def push(body: Push, request: Request):
    swarm = authorized(request.headers.get("authorization", ""))
    if not swarm:
        raise HTTPException(401, "Invalid installation credential")
    if set(body.data) != {"event_id", "kind"} or body.data["kind"] not in {"call", "task"}:
        raise HTTPException(400, "Only opaque event IDs and kind are allowed")
    try:
        uuid.UUID(body.data["event_id"])
    except ValueError:
        raise HTTPException(400, "Invalid event identifier")
    window = PUSH_WINDOWS[swarm["id"]]
    now = time.monotonic()
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= 30:
        raise HTTPException(429, "Push rate limit reached")
    window.append(now)
    def deliver():
        import firebase_admin
        from firebase_admin import messaging
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()
        return messaging.send(messaging.Message(token=body.token, data=body.data,
                              android=messaging.AndroidConfig(priority="high", ttl=45 if body.data["kind"] == "call" else 300)))
    try:
        await asyncio.to_thread(deliver)
    except Exception:
        raise HTTPException(503, "Push provider unavailable")
    return {"accepted": True}
