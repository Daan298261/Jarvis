"""Speak and post owner-chat notices when Jarvis is actually degraded."""
from __future__ import annotations

import json
from typing import Any

from ..config import data_dir
from ..persona.chat_delivery import publish_owner_text
from .self_check import run_self_check

_STATE_NAME = "health-notify.json"


def _state_path():
    return data_dir() / _STATE_NAME


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def issue_fingerprint(checks: list[dict[str, Any]]) -> str:
    parts = []
    for item in checks:
        status = str(item.get("status") or "")
        if status in {"ready", "starting"}:
            continue
        parts.append(f"{item.get('id')}:{status}:{item.get('detail')}")
    return " | ".join(parts)


def spoken_health_summary(checks: list[dict[str, Any]]) -> str:
    issues = [
        item
        for item in checks
        if str(item.get("status") or "") not in {"ready", "starting"}
    ]
    if not issues:
        return ""
    lines = [f"{item.get('label')}: {item.get('detail')}" for item in issues]
    if len(lines) == 1:
        return f"Jarvis is degraded. {lines[0]}"
    return f"Jarvis is degraded. {len(lines)} problems. " + " ".join(lines)


async def maybe_notify_health(*, force: bool = False) -> dict[str, Any]:
    snapshot = await run_self_check()
    checks = list(snapshot.get("checks") or [])
    fingerprint = issue_fingerprint(checks)
    state = _load_state()
    if not fingerprint:
        if state.get("fingerprint"):
            _save_state({"fingerprint": ""})
        return {"notified": False, "overall": snapshot.get("overall"), "fingerprint": ""}
    if not force and state.get("fingerprint") == fingerprint:
        return {"notified": False, "overall": snapshot.get("overall"), "fingerprint": fingerprint}
    text = spoken_health_summary(checks)
    delivery = await publish_owner_text(
        text,
        title="System status",
        kind="system",
        source="health",
        speak=True,
    )
    _save_state({"fingerprint": fingerprint, "text": text})
    return {
        "notified": True,
        "overall": snapshot.get("overall"),
        "fingerprint": fingerprint,
        "text": text,
        **delivery,
    }
