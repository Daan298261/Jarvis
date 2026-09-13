"""ChatGPT-style computer-use and cyber permission catalog (RFC-0079).

Grant modes: ask | allow_once | allow_session | always | deny.
Red flags are default-deny and still require the Red Team password gate.
Blue isolate is a containment playbook, not a kick/deauth executor.
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import data_dir

_STORE_FILE = "computer-permissions.json"
_LOCK = threading.RLock()
_SESSION_GRANTS: dict[str, str] = {}

GRANT_MODES = frozenset({"ask", "allow_once", "allow_session", "always", "deny"})
PROMPT_OPTIONS = ("allow_once", "allow_session", "always", "deny")

COMPUTER_TOOLS = frozenset({"desktop", "ufo", "cua"})
INTERNET_TOOLS = frozenset({"browser", "browser_use", "web_fetch"})
RDP_MARKERS = ("rdp", "mstsc", "remote desktop", "xfreerdp")
NODE_KEYS = ("node_id", "hostname", "worker_node", "target_node", "rdp_host")

_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_LOCAL_HOST_RE = re.compile(
    r"(localhost|127\.0\.0\.1|::1|\.local\b|home\.arpa\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PermissionSpec:
    id: str
    group: str
    title: str
    detail: str
    default: str
    gated: str | None = None
    offensive: bool = False


CATALOG: tuple[PermissionSpec, ...] = (
    PermissionSpec(
        "computer.this_device",
        "computer",
        "Use this computer",
        "Control the screen, keyboard, and apps on the machine running this Jarvis leader.",
        "ask",
    ),
    PermissionSpec(
        "computer.worker_nodes",
        "computer",
        "Use worker-node computers",
        "Delegate computer use to a swarm node that advertises desktop control.",
        "ask",
    ),
    PermissionSpec(
        "computer.rdp",
        "computer",
        "Open Remote Desktop",
        "From this Jarvis, launch an RDP client to a permitted worker node (mstsc). Not a new remote-control protocol.",
        "ask",
    ),
    PermissionSpec(
        "network.internet",
        "network",
        "Use the internet",
        "Browse or fetch public websites and WAN endpoints.",
        "ask",
    ),
    PermissionSpec(
        "network.local",
        "network",
        "Use the local network",
        "Talk to RFC1918 / localhost / .local hosts on networks you control.",
        "ask",
    ),
    PermissionSpec(
        "cyber.hexstrike",
        "cyber",
        "HexStrike AI suite",
        "Start and view the HexStrike cybersecurity suite through Jarvis. Command/payload endpoints stay blocked.",
        "ask",
    ),
    PermissionSpec(
        "blue.static_rules",
        "blue",
        "Blue team — static rules",
        "Apply owner-defined defensive detections and static allow/deny rules on this estate.",
        "ask",
        gated="blue-team",
    ),
    PermissionSpec(
        "blue.active_response",
        "blue",
        "Blue team — active response",
        "Allow defensive containment playbooks (alerts, host firewall, owned-LAN isolation plans).",
        "ask",
        gated="blue-team",
    ),
    PermissionSpec(
        "blue.isolate_device",
        "blue",
        "Blue team — isolate a device",
        "Plan isolation of a device on an owner-controlled LAN. Does not kick or deauth arbitrary hosts.",
        "ask",
        gated="blue-team",
    ),
    PermissionSpec(
        "red.entry",
        "red",
        "Red team — entry",
        "Permission flag only. Offensive entry is refused unless Taco or PolitieGPT under the LE gate adds it.",
        "deny",
        gated="red-team",
        offensive=True,
    ),
    PermissionSpec(
        "red.exploration",
        "red",
        "Red team — exploration",
        "Permission flag only. Offensive exploration is refused. No payloads or exploit steps.",
        "deny",
        gated="red-team",
        offensive=True,
    ),
)

CATALOG_BY_ID = {item.id: item for item in CATALOG}

BLUE_ISOLATE_PLAYBOOK = (
    "Confirm the target is listed in the owner inventory and sits on a LAN you control.",
    "Record MAC/IP from that inventory; do not scan unowned networks.",
    "If a managed AP or switch is available, apply an isolation VLAN or client-isolation ACL on that gear.",
    "If the worker node is Windows, add a host-firewall block for that inventory address only.",
    "Write an audit event. Do not deauth, kick, or disrupt devices you do not own.",
)


@dataclass
class PermissionDecision:
    permission_id: str
    status: str
    reason: str
    spec: PermissionSpec | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allow"


@dataclass
class ToolPermissionDecision:
    status: str
    reason: str
    pending: list[str] = field(default_factory=list)
    decisions: list[PermissionDecision] = field(default_factory=list)

    @property
    def requires_prompt(self) -> bool:
        return self.status == "ask"


def permissions_path() -> Path:
    path = data_dir() / _STORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_computer_permission_state() -> None:
    with _LOCK:
        _SESSION_GRANTS.clear()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "grants": {}}


def _load_store_unlocked() -> dict[str, Any]:
    path = permissions_path()
    if not path.exists():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    grants = raw.get("grants")
    if not isinstance(grants, dict):
        grants = {}
    return {"version": 1, "grants": grants}


def _save_store_unlocked(store: dict[str, Any]) -> None:
    permissions_path().write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _gate_enabled(role: str | None) -> bool:
    if not role:
        return True
    from ..inference.security_gates import gate_is_enabled

    try:
        return bool(gate_is_enabled(role))
    except KeyError:
        return False


def get_spec(permission_id: str) -> PermissionSpec:
    spec = CATALOG_BY_ID.get(permission_id)
    if spec is None:
        raise KeyError(permission_id)
    return spec


def persisted_mode(permission_id: str) -> str:
    spec = get_spec(permission_id)
    with _LOCK:
        store = _load_store_unlocked()
        record = store["grants"].get(permission_id)
    if isinstance(record, dict):
        mode = str(record.get("mode") or "").strip().lower()
        if mode in {"always", "deny", "ask"}:
            return mode
    return spec.default


def apply_grant(permission_id: str, mode: str, *, persist: bool | None = None) -> dict[str, Any]:
    spec = get_spec(permission_id)
    normalized = str(mode or "").strip().lower()
    if normalized not in GRANT_MODES:
        raise ValueError(f"unsupported grant mode: {mode}")
    if spec.offensive and normalized in {"allow_once", "allow_session", "always"}:
        if not _gate_enabled(spec.gated):
            raise PermissionError(
                f"{spec.title} stays denied until the Red Team password gate is unlocked. "
                "This flag does not add offensive tools."
            )
    if spec.gated and spec.group == "blue" and normalized in {"allow_once", "allow_session", "always"}:
        if not _gate_enabled(spec.gated):
            raise PermissionError(
                f"{spec.title} requires the Blue Team password gate to be unlocked."
            )
    if persist is None:
        persist = normalized in {"always", "deny", "ask"}
    with _LOCK:
        if normalized in {"allow_once", "allow_session"}:
            _SESSION_GRANTS[permission_id] = normalized
        elif permission_id in _SESSION_GRANTS:
            del _SESSION_GRANTS[permission_id]
        if persist:
            store = _load_store_unlocked()
            if normalized == "ask":
                store["grants"].pop(permission_id, None)
            else:
                store["grants"][permission_id] = {"mode": normalized, "updated_at": _utcnow()}
            _save_store_unlocked(store)
    return describe_permission(permission_id)


def operator_intent_grant(permission_id: str, mode: str = "allow_session") -> dict[str, Any]:
    """Treat an explicit owner UI action (suite start, settings save) as a grant when asking."""
    decision = evaluate_permission(permission_id)
    if decision.status == "deny" and persisted_mode(permission_id) == "deny":
        raise PermissionError(decision.reason)
    if decision.status == "allow":
        return describe_permission(permission_id)
    return apply_grant(permission_id, mode, persist=mode in {"always", "deny", "ask"})


def consume_once_grants(permission_ids: list[str]) -> None:
    with _LOCK:
        for permission_id in permission_ids:
            if _SESSION_GRANTS.get(permission_id) == "allow_once":
                _SESSION_GRANTS.pop(permission_id, None)


def evaluate_permission(permission_id: str) -> PermissionDecision:
    spec = get_spec(permission_id)
    if spec.gated and not _gate_enabled(spec.gated):
        if spec.offensive or spec.default == "deny":
            return PermissionDecision(
                permission_id,
                "deny",
                f"{spec.title} is locked. Unlock the {spec.gated} password gate first. "
                + ("Offensive tools are not shipped with this flag." if spec.offensive else ""),
                spec,
            )
        return PermissionDecision(
            permission_id,
            "deny",
            f"{spec.title} requires the {spec.gated} password gate to be unlocked.",
            spec,
        )
    persisted = persisted_mode(permission_id)
    if persisted == "deny":
        return PermissionDecision(permission_id, "deny", f"{spec.title} is set to Don't allow.", spec)
    if persisted == "always":
        return PermissionDecision(permission_id, "allow", f"{spec.title} is Always allowed.", spec)
    with _LOCK:
        session_mode = _SESSION_GRANTS.get(permission_id)
    if session_mode in {"allow_session", "allow_once"}:
        label = "this session" if session_mode == "allow_session" else "once"
        return PermissionDecision(permission_id, "allow", f"{spec.title} is allowed {label}.", spec)
    if persisted == "ask" or spec.default == "ask":
        return PermissionDecision(permission_id, "ask", f"{spec.title} needs your approval.", spec)
    return PermissionDecision(permission_id, "deny", f"{spec.title} is not allowed.", spec)


def describe_permission(permission_id: str) -> dict[str, Any]:
    spec = get_spec(permission_id)
    decision = evaluate_permission(permission_id)
    persisted = persisted_mode(permission_id)
    with _LOCK:
        session_mode = _SESSION_GRANTS.get(permission_id)
    return {
        "id": spec.id,
        "group": spec.group,
        "title": spec.title,
        "detail": spec.detail,
        "default": spec.default,
        "gated": spec.gated,
        "offensive": spec.offensive,
        "persisted": persisted,
        "session": session_mode,
        "status": decision.status,
        "reason": decision.reason,
        "gate_unlocked": _gate_enabled(spec.gated),
        "options": list(PROMPT_OPTIONS),
    }


def catalog_snapshot() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for spec in CATALOG:
        groups.setdefault(spec.group, []).append(describe_permission(spec.id))
    return {
        "permissions": [describe_permission(spec.id) for spec in CATALOG],
        "groups": groups,
        "options": list(PROMPT_OPTIONS),
    }


def _blob(arguments: dict[str, Any] | None) -> str:
    if not arguments:
        return ""
    try:
        return json.dumps(arguments, sort_keys=True).lower()
    except TypeError:
        return str(arguments).lower()


def _host_is_local(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    if _LOCAL_HOST_RE.search(text):
        return True
    host = text
    parsed = urlparse(text if "://" in text else f"//{text}", scheme="http")
    if parsed.hostname:
        host = parsed.hostname
    host = host.split("%")[0]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local") or host in {"localhost", "host.docker.internal"}
    return any(addr in net for net in _PRIVATE_NETS)


def looks_local_network(arguments: dict[str, Any] | None) -> bool:
    blob = _blob(arguments)
    if not blob:
        return False
    if _LOCAL_HOST_RE.search(blob):
        return True
    for key in ("url", "uri", "host", "hostname", "address", "target"):
        value = (arguments or {}).get(key)
        if isinstance(value, str) and _host_is_local(value):
            return True
    return False


def looks_remote_node(arguments: dict[str, Any] | None) -> bool:
    args = arguments or {}
    if any(args.get(key) for key in NODE_KEYS):
        return True
    blob = _blob(args)
    return any(marker in blob for marker in ("worker node", "swarm node", "node_id"))


def looks_rdp(arguments: dict[str, Any] | None) -> bool:
    blob = _blob(arguments)
    if any(marker in blob for marker in RDP_MARKERS):
        return True
    args = arguments or {}
    return bool(args.get("rdp") or args.get("rdp_host"))


def permission_ids_for_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> list[str]:
    name = (tool_name or "").strip().lower()
    pending: list[str] = []
    if name in COMPUTER_TOOLS:
        if looks_rdp(arguments):
            pending.append("computer.rdp")
        if looks_remote_node(arguments) or looks_rdp(arguments):
            pending.append("computer.worker_nodes")
        else:
            pending.append("computer.this_device")
    if name in INTERNET_TOOLS:
        pending.append("network.local" if looks_local_network(arguments) else "network.internet")
    if name in {"hexstrike", "hexstrike_suite"}:
        pending.append("cyber.hexstrike")
    # unique, stable order following catalog
    order = [spec.id for spec in CATALOG]
    return [item for item in order if item in set(pending)]


def evaluate_tool_permissions(tool_name: str, arguments: dict[str, Any] | None = None) -> ToolPermissionDecision:
    ids = permission_ids_for_tool(tool_name, arguments)
    if not ids:
        return ToolPermissionDecision("allow", "no extra computer-use permission required")
    decisions = [evaluate_permission(item) for item in ids]
    denied = [item for item in decisions if item.status == "deny"]
    if denied:
        return ToolPermissionDecision(
            "deny",
            denied[0].reason,
            pending=[item.permission_id for item in denied],
            decisions=decisions,
        )
    asking = [item for item in decisions if item.status == "ask"]
    if asking:
        return ToolPermissionDecision(
            "ask",
            asking[0].reason,
            pending=[item.permission_id for item in asking],
            decisions=decisions,
        )
    return ToolPermissionDecision(
        "allow",
        "computer-use permissions granted",
        pending=[],
        decisions=decisions,
    )


_SPOKEN_ASKS: dict[str, str] = {
    "network.internet": "Sir, I need your permission to search the internet. Do you grant it?",
    "network.local": "Sir, I need your permission to use the local network. Do you grant it?",
    "computer.this_device": "Sir, I need your permission to use this computer. Do you grant it?",
    "computer.worker_nodes": "Sir, I need your permission to use a worker-node computer. Do you grant it?",
    "computer.rdp": "Sir, I need your permission to open Remote Desktop. Do you grant it?",
    "cyber.hexstrike": "Sir, I need your permission to use the HexStrike suite. Do you grant it?",
    "blue.static_rules": "Sir, I need your permission to apply blue-team static rules. Do you grant it?",
    "blue.active_response": "Sir, I need your permission for blue-team active response. Do you grant it?",
    "blue.isolate_device": "Sir, I need your permission to plan isolating a device. Do you grant it?",
    "red.entry": "Sir, red-team entry is a permission flag only. Do you grant it?",
    "red.exploration": "Sir, red-team exploration is a permission flag only. Do you grant it?",
}

_DENY_RE = re.compile(
    r"\b(no|nope|nah|deny|denied|refuse|refused|cancel|stop|never|don'?t|dont)\b|"
    r"do not|not now",
    re.IGNORECASE,
)
_ALWAYS_RE = re.compile(r"\b(always|every time|from now on|remember this)\b", re.IGNORECASE)
_SESSION_RE = re.compile(r"\b(this session|for this session|just this session|for now)\b", re.IGNORECASE)
_ALLOW_RE = re.compile(
    r"\b(yes|yeah|yep|yup|allow|allowed|proceed|okay|ok|sure|certainly|affirmative)\b|"
    r"go ahead|of course|i grant|grant(?:ed)? (?:it|permission|this)|you may",
    re.IGNORECASE,
)


def spoken_prompt_for_permission(permission_id: str, pending: list[str] | None = None) -> str:
    """Original household-aide ask. Not a copyrighted character line."""
    primary = _SPOKEN_ASKS.get(permission_id) or (
        f"Sir, I need your permission for {permission_id.replace('.', ' ')}. Do you grant it?"
    )
    extra = [item for item in (pending or []) if item != permission_id]
    if extra:
        return primary.replace(" Do you grant it?", " Further permissions are listed on screen. Do you grant it?")
    return primary


def interpret_spoken_grant(transcript: str) -> str | None:
    """Map a short spoken reply to a grant mode. Returns None when unclear."""
    cleaned = re.sub(r"[^a-z0-9\s']+", " ", (transcript or "").lower())
    cleaned = re.sub(r"\bdo you grant(?: it)?\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    denied = bool(_DENY_RE.search(cleaned))
    if _ALWAYS_RE.search(cleaned) and not denied:
        return "always"
    if _SESSION_RE.search(cleaned) and not denied:
        return "allow_session"
    if denied:
        return "deny"
    if _ALLOW_RE.search(cleaned):
        return "allow_once"
    return None


def confirmation_payload_for_tool(
    *,
    call_id: str,
    name: str,
    arguments: dict[str, Any] | None,
    irreversible: bool = False,
) -> dict[str, Any]:
    decision = evaluate_tool_permissions(name, arguments)
    payload: dict[str, Any] = {
        "id": call_id,
        "name": name,
        "arguments": arguments or {},
        "irreversible": irreversible,
    }
    if decision.requires_prompt and decision.pending:
        primary = get_spec(decision.pending[0])
        payload.update(
            {
                "kind": "permission",
                "permission_id": primary.id,
                "pending": decision.pending,
                "title": primary.title,
                "detail": primary.detail,
                "reason": decision.reason,
                "options": list(PROMPT_OPTIONS),
                "catalog": [describe_permission(item) for item in decision.pending],
                "spoken_prompt": spoken_prompt_for_permission(primary.id, decision.pending),
                "voice_reply_hint": "Say yes, always, or no.",
            }
        )
    else:
        payload["kind"] = "destructive" if irreversible else "confirm"
        payload["title"] = "Approve this action"
        payload["detail"] = f"Jarvis wants to run {name}."
        if irreversible:
            payload["spoken_prompt"] = (
                "Sir, this can delete or irreversibly change files. Do you approve?"
            )
        else:
            payload["spoken_prompt"] = f"Sir, I need your permission to run {name}. Do you grant it?"
        payload["voice_reply_hint"] = "Say yes or no."
    return payload


def blue_isolate_playbook(*, device: str, reason: str = "") -> dict[str, Any]:
    decision = evaluate_permission("blue.isolate_device")
    target = (device or "").strip()
    if not target:
        raise ValueError("device is required")
    return {
        "allowed": decision.status == "allow",
        "status": decision.status,
        "reason": decision.reason,
        "device": target,
        "request_reason": reason,
        "executed": False,
        "steps": list(BLUE_ISOLATE_PLAYBOOK),
        "note": "Jarvis records a containment plan for an owned-LAN device. It does not kick hosts off the network.",
    }
