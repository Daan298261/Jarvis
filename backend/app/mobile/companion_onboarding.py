"""Spoken onboarding hooks for companion pairing (RFC-0074)."""
from __future__ import annotations

from typing import Any

from ..auth import get_effective_private_key
from ..config import load_settings
from ..persona.quiet import should_speak_chat_reply
from .connectivity import CONNECTIVITY
from .identity import pairing_code_status
from .store import database, rows


def companion_onboarding_snapshot() -> dict[str, Any]:
    settings = load_settings()
    connection = CONNECTIVITY.snapshot()
    pairing = pairing_code_status()
    with database() as db:
        device_count = len(rows(db, "device"))
        pending = sum(1 for device in rows(db, "device") if device.get("status") == "pending")
    has_key = bool(get_effective_private_key(settings))
    connection_ready = connection.get("state") == "ready" and bool(connection.get("endpoints"))
    offers: list[dict[str, Any]] = []

    pair_prompt = (
        "I can walk you through pairing your phone. Open Pair phone on this desktop, "
        "then scan the QR code or enter the six-digit code on your phone."
    )
    if not connection_ready:
        pair_prompt = (
            "To pair your phone, first choose Prepare connection in the companion settings, "
            "then open Pair phone for the code and QR."
        )
    offers.append(
        {
            "id": "pair_phone",
            "label": "Pair your phone",
            "spoken_prompt": pair_prompt,
            "hint": "companion_pairing",
        }
    )
    offers.append(
        {
            "id": "explore_features",
            "label": "Explore what Jarvis can do",
            "spoken_prompt": (
                "We can skip phone setup for now. Tell me what you would like to try, "
                "or ask me to walk through setup at your own pace."
            ),
            "hint": "conversational_onboarding",
        }
    )

    return {
        "version": 1,
        "owner_key_configured": has_key,
        "paired_device_count": device_count,
        "pending_device_count": pending,
        "speak_chat_replies": should_speak_chat_reply(settings),
        "connection": {
            "state": connection.get("state", "disabled"),
            "activity": connection.get("activity", ""),
            "endpoints": connection.get("endpoints") or [],
            "server_pin": connection.get("server_pin", ""),
            "ready": connection_ready,
        },
        "pairing": pairing,
        "offers": offers,
    }
