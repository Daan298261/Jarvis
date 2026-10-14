"""Owner-selected Chrome tab, transported by an optional native messaging host."""
from __future__ import annotations

import asyncio
import base64
import json
import math
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .base import ToolResult

ACTIONS = frozenset({"chrome_status", "chrome_snapshot", "chrome_find", "chrome_click", "chrome_fill", "chrome_block_ads", "chrome_frames", "chrome_upload", "chrome_download"})


def connector_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ANZU" / "chrome-connector"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    temp.replace(path)


async def execute_connector(action: str, **arguments) -> ToolResult:
    if action not in ACTIONS:
        return ToolResult(False, "", error="Unknown Chrome connector action")
    root = connector_dir()
    state = read_json(root / "connection.json")
    try:
        age = time.time() - float(state.get("heartbeat", 0))
        connected = bool(state.get("session")) and 0 <= age < 5
    except (TypeError, ValueError):
        connected = False
    if action == "chrome_status":
        return ToolResult(True, "Chrome connector connected" if connected else "Chrome connector disconnected; open the extension and share a tab.", data={"connected": connected, "shared_url": state.get("url") if connected else None})
    if not connected:
        return ToolResult(False, "", error="Chrome connector is disconnected. Install the extension/native host and share a tab in Chrome.")
    url = str(arguments.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ToolResult(False, "", error="An exact HTTP(S) URL of the shared Chrome tab is required; credentials in URLs are refused.")
    from ..policy.computer_permissions import evaluate_tool_permissions

    gate = evaluate_tool_permissions("browser", {"url": url, "action": action})
    if gate.status != "allow":
        return ToolResult(False, "", error=gate.reason or "Browser permission required")
    if action in {"chrome_click", "chrome_fill", "chrome_upload", "chrome_download"} and not str(arguments.get("target_id") or "").strip():
        return ToolResult(False, "", error="target_id from a fresh chrome_snapshot is required")
    if action == "chrome_find" and not str(arguments.get("text") or "").strip():
        return ToolResult(False, "", error="text is required")
    if action == "chrome_block_ads" and not isinstance(arguments.get("enabled"), bool):
        return ToolResult(False, "", error="enabled must be true or false")
    if len(str(arguments.get("text") or "")) > 16000 or len(url) > 8000:
        return ToolResult(False, "", error="Chrome text or URL exceeds the connector limit")
    try:
        timeout = float(arguments.get("timeout_seconds", 15))
        if not math.isfinite(timeout):
            raise ValueError
        timeout = min(30, max(1, timeout))
    except (TypeError, ValueError):
        return ToolResult(False, "", error="timeout_seconds must be a finite number")
    frame_id = arguments.get("frame_id", 0)
    if not isinstance(frame_id, int) or isinstance(frame_id, bool) or frame_id < 0:
        return ToolResult(False, "", error="frame_id must be a non-negative integer")
    for key in ("frame_url", "download_url"):
        target = str(arguments.get(key) or "")
        if (key == "frame_url" and frame_id) or (key == "download_url" and action == "chrome_download"):
            parsed_target = urlparse(target)
            if parsed_target.scheme not in {"http", "https"} or not parsed_target.hostname or parsed_target.username or parsed_target.password:
                return ToolResult(False, "", error=f"An exact HTTP(S) {key} is required")
            extra_gate = evaluate_tool_permissions("browser", {"url": target, "action": action})
            if extra_gate.status != "allow":
                return ToolResult(False, "", error=extra_gate.reason or "Browser permission required")
    payload = {"action": action, "url": url, "frame_id": frame_id}
    for key in ("target_id", "text", "enabled", "frame_url", "download_url"):
        if key in arguments:
            payload[key] = arguments[key]
    if not frame_id:
        payload.pop("frame_url", None)
    if action == "chrome_upload":
        from .safety import resolve_allowed_path
        try:
            path = Path(resolve_allowed_path(str(arguments.get("path") or ""), arguments.get("_allowed", [])))
            if not path.is_file():
                raise ValueError("Upload path must be a file")
            size = path.stat().st_size
            if size > 20 * 1024 * 1024:
                raise ValueError("Chrome uploads are limited to 20 MiB")
            upload_id = uuid.uuid4().hex
            payload.update(upload_id=upload_id, filename=path.name, mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream", size=size)
            result = await _send(root, state, {**payload, "stage": "begin"}, timeout)
            if not result.success:
                return result
            with path.open("rb") as source:
                while chunk := source.read(192 * 1024):
                    result = await _send(root, state, {**payload, "stage": "chunk", "chunk": base64.b64encode(chunk).decode("ascii")}, timeout)
                    if not result.success:
                        return result
            return await _send(root, state, {**payload, "stage": "finish"}, timeout)
        except (OSError, ValueError, PermissionError) as exc:
            return ToolResult(False, "", error=str(exc))
    result = await _send(root, state, payload, timeout)
    if action == "chrome_download" and result.success:
        final_url = str(result.data.get("url") or "")
        if final_url:
            final_gate = evaluate_tool_permissions("browser", {"url": final_url, "action": action})
            if final_gate.status != "allow":
                return ToolResult(False, "", error=final_gate.reason or "Download redirected to an unapproved URL")
    return result


async def _send(root: Path, state: dict, payload: dict, timeout: float) -> ToolResult:
    request_id = uuid.uuid4().hex
    request = root / f"{request_id}.request.json"
    response = root / f"{request_id}.response.json"
    expires = time.time() + timeout
    payload = {**payload, "id": request_id, "session": state["session"], "expires": expires}
    atomic_json(request, payload)
    try:
        while time.time() < expires:
            if response.exists():
                reply = read_json(response)
                if reply.get("id") != request_id:
                    return ToolResult(False, "", error="Invalid Chrome response")
                return ToolResult(bool(reply.get("success")), str(reply.get("output") or ""), data=reply.get("data") or {}, error=str(reply.get("error") or ""))
            live = read_json(root / "connection.json")
            if live.get("session") != state["session"]:
                return ToolResult(False, "", error="Chrome connector disconnected during the operation; inspect the page before retrying.")
            await asyncio.sleep(0.05)
        return ToolResult(False, "", error="Chrome connector timed out. A dispatched action may have completed; inspect the page before retrying.")
    finally:
        request.unlink(missing_ok=True)
        response.unlink(missing_ok=True)
