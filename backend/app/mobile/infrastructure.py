"""Operator infrastructure readiness (booleans only; never exposes secrets)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

_FIREBASE_PUBLIC_KEYS = frozenset({"app_id", "api_key", "project_id", "sender_id"})


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _https_origin(value: str) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and not parsed.path.strip("/")
    )


def _https_push_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _relay_hostname_present() -> bool:
    for name in ("JARVIS_RELAY_URL", "JARVIS_RELAY_ENDPOINT"):
        host = urlsplit(_env(name)).hostname
        if host:
            return True
    return False


def firebase_client_config_ready() -> bool:
    path_value = _env("JARVIS_FIREBASE_CLIENT_CONFIG")
    if not path_value:
        return False
    path = Path(path_value)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return _FIREBASE_PUBLIC_KEYS.issubset(payload.keys()) and all(
        isinstance(payload[key], str) and payload[key].strip() for key in _FIREBASE_PUBLIC_KEYS
    )


def infrastructure_readiness() -> dict[str, bool]:
    relay_url = _env("JARVIS_RELAY_URL")
    relay_credential = _env("JARVIS_RELAY_CREDENTIAL")
    relay_endpoint = _env("JARVIS_RELAY_ENDPOINT")
    push_url = _env("JARVIS_PUSH_URL")
    push_credential = _env("JARVIS_PUSH_CREDENTIAL")
    turn_url = _env("JARVIS_TURN_URL")
    turn_secret = _env("JARVIS_TURN_SECRET")
    return {
        "relay_agent_configured": bool(relay_url and relay_credential and _https_origin(relay_url)),
        "relay_endpoint_configured": bool(relay_endpoint and _https_origin(relay_endpoint)),
        "relay_hostname_present": _relay_hostname_present(),
        "push_configured": bool(push_url and push_credential and _https_push_url(push_url)),
        "turn_configured": bool(turn_url and turn_secret),
        "firebase_client_config_configured": firebase_client_config_ready(),
    }
