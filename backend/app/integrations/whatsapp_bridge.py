"""Bridge to the paired WhatsApp Web session (wappmcp) for media/text sends."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from ..config import repo_root
from .setup import WHATSAPP_PAIRING, _chrome_executable, _node_executable, whatsapp_home


_PHONE_RE = re.compile(r"[^\d+]")


def _helper() -> Path:
    return repo_root() / "mcp" / "whatsapp-action.mjs"


def _connector_dir() -> Path:
    return repo_root() / "mcp" / "node_modules" / "wappmcp"


def require_whatsapp_paired() -> None:
    status = WHATSAPP_PAIRING.status()
    if not bool(status.get("paired") or status.get("state") == "connected"):
        raise HTTPException(400, "WhatsApp is not connected. Connect WhatsApp in Setup, then try again.")
    if not _helper().is_file() or not _connector_dir().is_dir():
        raise HTTPException(500, "The WhatsApp connector is missing. Re-run the Jarvis installer.")
    if not _chrome_executable():
        raise HTTPException(400, "Google Chrome is required for WhatsApp. Install Chrome and try again.")


def normalize_phone(value: str) -> str:
    cleaned = _PHONE_RE.sub("", (value or "").strip())
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or not (8 <= len(cleaned) <= 15):
        raise HTTPException(400, "Enter a valid phone number with country code (digits only).")
    return cleaned


def chat_id_from_phone(phone: str) -> str:
    digits = normalize_phone(phone)
    return f"{digits}@c.us"


async def _run_action(payload: dict[str, Any], *, timeout: float = 180.0) -> dict[str, Any]:
    require_whatsapp_paired()
    env = os.environ.copy()
    env["WAPPMCP_HOME"] = str(whatsapp_home())
    chrome = _chrome_executable()
    if chrome:
        env["WAPPMCP_BROWSER_PATH"] = chrome
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome
    process = await asyncio.create_subprocess_exec(
        _node_executable(),
        str(_helper()),
        json.dumps(payload),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(repo_root() / "mcp"),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise HTTPException(504, "WhatsApp timed out. Keep the phone online and try again.") from exc

    lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        detail = stderr.decode("utf-8", errors="replace").strip() or "WhatsApp returned no response."
        raise HTTPException(502, detail[:300])
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "WhatsApp returned an invalid response.") from exc
    if not result.get("ok"):
        message = str(result.get("error") or "WhatsApp action failed.")
        raise HTTPException(502, message[:300])
    return result


async def whatsapp_me() -> dict[str, Any]:
    return await _run_action({"action": "me"})


async def resolve_chat_id(to: str | None = None) -> str:
    target = (to or "").strip()
    if target:
        if "@" in target:
            return target
        looked = await _run_action({"action": "lookup", "q": normalize_phone(target)})
        if looked.get("id"):
            return str(looked["id"])
        if looked.get("registered") is False:
            raise HTTPException(400, "That phone number is not on WhatsApp.")
        return chat_id_from_phone(target)
    me = await whatsapp_me()
    chat_id = str(me.get("id") or "").strip()
    if chat_id:
        return chat_id
    number = str(me.get("number") or "").strip()
    if number:
        return chat_id_from_phone(number)
    raise HTTPException(502, "Could not resolve the WhatsApp chat for this account.")


async def send_whatsapp_media(path: Path, *, to: str | None = None, caption: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(404, "File is missing on disk")
    chat_id = await resolve_chat_id(to)
    result = await _run_action(
        {
            "action": "send_media",
            "chatId": chat_id,
            "path": str(path.resolve()),
            "caption": caption or "",
        },
        timeout=240.0,
    )
    return {
        "ok": "true",
        "channel": "whatsapp",
        "chat_id": chat_id,
        "message_id": str(result.get("messageId") or ""),
        "detail": "File sent on WhatsApp.",
    }


async def send_whatsapp_text(text: str, *, to: str | None = None) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        raise HTTPException(400, "Message text is required.")
    chat_id = await resolve_chat_id(to)
    result = await _run_action({"action": "send_text", "chatId": chat_id, "text": body})
    return {
        "ok": "true",
        "channel": "whatsapp",
        "chat_id": chat_id,
        "message_id": str(result.get("messageId") or ""),
        "detail": "Message sent on WhatsApp.",
    }


async def jarvis_whatsapp_contact() -> dict[str, Any]:
    """Contact card the companion can save so the owner can message Jarvis on WhatsApp."""
    require_whatsapp_paired()
    me = await whatsapp_me()
    number = normalize_phone(str(me.get("number") or ""))
    name = str(me.get("pushname") or me.get("name") or "Jarvis").strip() or "Jarvis"
    note = (
        "Message this chat to talk to Jarvis. Your desktop WhatsApp link receives the messages "
        "while Jarvis is running."
    )
    return {
        "available": True,
        "display_name": "Jarvis",
        "account_name": name,
        "phone_e164": f"+{number}",
        "phone_digits": number,
        "chat_id": str(me.get("id") or chat_id_from_phone(number)),
        "wa_me_url": f"https://wa.me/{number}?text={quote('Hi Jarvis')}",
        "note": note,
    }
