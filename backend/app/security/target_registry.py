"""RFC-0197 owner-scoped security target registry.

Default-deny for HexStrike operate and red/blue offensive-adjacent paths.
No exploit recipes, payloads, or attack procedures.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from ..config import data_dir, default_allowed_directories, load_settings
from .security_audit import audit_security_event

_LOCK = threading.RLock()
_REGISTRY_NAME = "security-targets.json"
_CONTAINER_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+|@sha256:[a-f0-9]{64})?$", re.I)
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$", re.I)

TARGET_KINDS = frozenset({"hostname", "ipv4", "ipv6", "cidr", "local_path", "container_image"})

# Argument keys that indicate a third-party / host target on operate paths.
_TARGET_ARG_KEYS = (
    "target",
    "host",
    "hostname",
    "ip",
    "ipv4",
    "ipv6",
    "cidr",
    "address",
    "url",
    "image",
    "container_image",
    "path",
    "local_path",
    "value",
    "scope_id",
)


class TargetRegistryError(ValueError):
    pass


class TargetDenied(PermissionError):
    pass


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def registry_path() -> Path:
    path = data_dir() / _REGISTRY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_rows() -> list[dict[str, Any]]:
    path = registry_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("targets") or payload.get("rows") or []
        return [row for row in rows if isinstance(row, dict)]
    return []


def _write_rows(rows: list[dict[str, Any]]) -> None:
    path = registry_path()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps({"version": 1, "targets": rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _normalize_local_path(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise TargetRegistryError("local_path targets must be absolute")
    resolved = candidate.resolve(strict=False)
    settings = load_settings()
    roots = settings.allowed_directories or default_allowed_directories()
    from ..config import LOCAL_NETWORK_SCOPE

    allowed = [Path(root).expanduser().resolve(strict=False) for root in roots if root != LOCAL_NETWORK_SCOPE]
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise TargetRegistryError("local_path is outside Jarvis allowed directories")
    return str(resolved)


def normalize_target(kind: str, value: str) -> str:
    normalized_kind = (kind or "").strip().lower()
    cleaned = (value or "").strip()
    if normalized_kind not in TARGET_KINDS:
        raise TargetRegistryError(f"unsupported target kind: {kind}")
    if not cleaned:
        raise TargetRegistryError("target value is required")
    if normalized_kind == "hostname":
        host = cleaned.lower().rstrip(".")
        if host in {"localhost"}:
            return host
        if not _HOSTNAME_RE.fullmatch(host):
            raise TargetRegistryError("invalid hostname")
        return host
    if normalized_kind == "ipv4":
        try:
            return str(ipaddress.IPv4Address(cleaned))
        except ValueError as exc:
            raise TargetRegistryError("invalid ipv4 address") from exc
    if normalized_kind == "ipv6":
        try:
            return str(ipaddress.IPv6Address(cleaned))
        except ValueError as exc:
            raise TargetRegistryError("invalid ipv6 address") from exc
    if normalized_kind == "cidr":
        try:
            return str(ipaddress.ip_network(cleaned, strict=False))
        except ValueError as exc:
            raise TargetRegistryError("invalid cidr") from exc
    if normalized_kind == "local_path":
        return _normalize_local_path(cleaned)
    if not _CONTAINER_RE.fullmatch(cleaned):
        raise TargetRegistryError("invalid container_image reference")
    return cleaned


def list_targets() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_read_rows())


def get_target(target_id: str) -> dict[str, Any] | None:
    ident = (target_id or "").strip()
    if not ident:
        return None
    return next((row for row in list_targets() if str(row.get("id") or "") == ident), None)


def add_target(
    *,
    kind: str,
    value: str,
    notes: str = "",
    target_id: str | None = None,
) -> dict[str, Any]:
    normalized_kind = (kind or "").strip().lower()
    normalized_value = normalize_target(normalized_kind, value)
    ident = (target_id or "").strip() or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", ident):
        raise TargetRegistryError("invalid target id")
    now = _utcnow_iso()
    with _LOCK:
        rows = _read_rows()
        for row in rows:
            if str(row.get("kind") or "") == normalized_kind and str(row.get("value") or "") == normalized_value:
                raise TargetRegistryError("target already registered")
            if str(row.get("id") or "") == ident:
                raise TargetRegistryError("target id already exists")
        row = {
            "id": ident,
            "kind": normalized_kind,
            "value": normalized_value,
            "owner_attested_at": now,
            "notes": (notes or "").strip()[:240],
        }
        rows.append(row)
        _write_rows(rows)
    audit_security_event("target_added", target_id=ident, kind=normalized_kind, value=normalized_value)
    return row


def remove_target(target_id: str) -> dict[str, Any]:
    ident = (target_id or "").strip()
    if not ident:
        raise TargetRegistryError("target id is required")
    with _LOCK:
        rows = _read_rows()
        existing = next((row for row in rows if str(row.get("id") or "") == ident), None)
        if existing is None:
            raise KeyError(ident)
        _write_rows([row for row in rows if str(row.get("id") or "") != ident])
    audit_security_event(
        "target_removed",
        target_id=ident,
        kind=str(existing.get("kind") or ""),
        value=str(existing.get("value") or ""),
    )
    return existing


def _value_matches(registered: str, kind: str, candidate: str) -> bool:
    if registered == candidate:
        return True
    if kind == "cidr":
        try:
            network = ipaddress.ip_network(registered, strict=False)
            try:
                return ipaddress.ip_address(candidate) in network
            except ValueError:
                try:
                    return ipaddress.ip_network(candidate, strict=False).subnet_of(network)
                except ValueError:
                    return False
        except ValueError:
            return False
    if kind == "hostname":
        return registered.lower() == candidate.lower().rstrip(".")
    return False


def is_registered_value(value: str, *, kind: str | None = None) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return False
    for row in list_targets():
        row_kind = str(row.get("kind") or "")
        if kind and row_kind != kind:
            continue
        if _value_matches(str(row.get("value") or ""), row_kind, cleaned):
            return True
    return False


def is_registered_id(target_id: str) -> bool:
    return get_target(target_id) is not None


def _guess_kinds(value: str) -> list[str]:
    cleaned = (value or "").strip()
    if not cleaned:
        return []
    kinds: list[str] = []
    try:
        ipaddress.IPv4Address(cleaned)
        kinds.append("ipv4")
    except ValueError:
        pass
    try:
        ipaddress.IPv6Address(cleaned)
        kinds.append("ipv6")
    except ValueError:
        pass
    try:
        ipaddress.ip_network(cleaned, strict=False)
        kinds.append("cidr")
    except ValueError:
        pass
    if cleaned.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", cleaned) or cleaned.startswith("\\\\"):
        kinds.append("local_path")
    if _CONTAINER_RE.fullmatch(cleaned) and ("/" in cleaned or ":" in cleaned):
        kinds.append("container_image")
    if _HOSTNAME_RE.fullmatch(cleaned.rstrip(".")) or cleaned.lower() == "localhost":
        kinds.append("hostname")
    return kinds


def extract_target_candidates(arguments: dict[str, Any] | None) -> list[dict[str, str]]:
    """Pull target-like fields from HexStrike/tool arguments (no payloads)."""
    args = arguments if isinstance(arguments, dict) else {}
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind_hint: str, raw: str) -> None:
        value = (raw or "").strip()
        if not value:
            return
        key = (kind_hint, value)
        if key in seen:
            return
        seen.add(key)
        found.append({"kind_hint": kind_hint, "value": value})

    for key in _TARGET_ARG_KEYS:
        if key not in args:
            continue
        raw = args.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if key == "scope_id":
            try:
                from .hexstrike_defensive import get_scope

                scope = get_scope(text)
                _add(str(scope.get("kind") or "scope"), str(scope.get("value") or ""))
            except Exception:
                _add("scope_id", text)
            continue
        hint = {
            "host": "hostname",
            "hostname": "hostname",
            "ip": "ipv4",
            "ipv4": "ipv4",
            "ipv6": "ipv6",
            "cidr": "cidr",
            "image": "container_image",
            "container_image": "container_image",
            "path": "local_path",
            "local_path": "local_path",
            "url": "hostname",
            "address": "hostname",
            "target": "",
            "value": "",
        }.get(key, "")
        if key == "url":
            # host portion only — never store credentials/paths as attack recipes
            host = text
            if "://" in host:
                host = host.split("://", 1)[1]
            host = host.split("/", 1)[0].split("@")[-1].split(":")[0]
            _add("hostname", host)
            continue
        if hint:
            _add(hint, text)
        else:
            for guessed in _guess_kinds(text) or [""]:
                _add(guessed, text)
    return found


def assert_targets_allowed(
    arguments: dict[str, Any] | None,
    *,
    security_role: str = "",
    capability_id: str = "",
    source: str = "hexstrike_operate",
) -> None:
    """Default-deny: any target-like argument must match the owner registry."""
    candidates = extract_target_candidates(arguments)
    if not candidates:
        return
    for item in candidates:
        value = item["value"]
        kind_hint = item.get("kind_hint") or None
        allowed = False
        if kind_hint == "scope_id":
            allowed = is_registered_id(value) or is_registered_value(value)
        elif kind_hint:
            allowed = is_registered_value(value, kind=kind_hint) or is_registered_value(value)
        else:
            allowed = is_registered_value(value)
        if allowed:
            continue
        audit_security_event(
            "invoke_denied",
            reason="target_not_registered",
            value=value,
            kind_hint=kind_hint or "",
            security_role=security_role or "",
            capability_id=capability_id or "",
            source=source,
        )
        raise TargetDenied(
            "target is not in the owner-attested security registry; "
            "add it under security targets before operate"
        )


def assert_value_allowed(
    value: str,
    *,
    kind: str | None = None,
    security_role: str = "",
    capability_id: str = "",
    source: str = "security_tool",
) -> None:
    if is_registered_value(value, kind=kind) or (kind is None and is_registered_value(value)):
        return
    audit_security_event(
        "invoke_denied",
        reason="target_not_registered",
        value=(value or "").strip(),
        kind_hint=kind or "",
        security_role=security_role or "",
        capability_id=capability_id or "",
        source=source,
    )
    raise TargetDenied(
        "target is not in the owner-attested security registry; "
        "add it under security targets before operate"
    )
