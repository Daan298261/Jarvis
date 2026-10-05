"""Register local REA MCP (io.github.morluto/rea) into Jarvis Connections (RFC-0200)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import load_settings, save_settings
from ..integrations.setup import ensure_mcp_preset
from ..tools.mcp_runtime import MCP
from .rea_paths import (
    mcp_investigation_roots_json,
    suppressed_dynamic_rea_envs,
)
from .security_audit import audit_security_event

log = logging.getLogger(__name__)

REA_MCP_SERVER_NAME = "rea"
REA_MCP_CATALOG_KEY = "io.github.morluto/rea"
REA_AGENTS_PIN = "3.2.1"
REA_ENABLE_PERMISSION = "cyber.rea_mcp"
REA_NEW_ROOT_PERMISSION = "cyber.rea_new_root"

_MCP_STATUS: dict[str, str] = {}
_MCP_LAST_ERROR = ""


@dataclass
class McpRegistrationResult:
    ok: bool
    servers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    transport: str = "stdio"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "servers": dict(self.servers),
            "error": self.error,
            "transport": self.transport,
            "catalog_key": REA_MCP_CATALOG_KEY,
        }


def mcp_registration_status() -> dict[str, str]:
    return dict(_MCP_STATUS)


def mcp_registration_error() -> str:
    return _MCP_LAST_ERROR


def rea_package_pin() -> str:
    settings = load_settings()
    pin = str(settings.rea.package_version or "").strip() or REA_AGENTS_PIN
    if any(ch in pin for ch in (" ", "/", "\\", ";", "|", "&")):
        return REA_AGENTS_PIN
    return pin


def build_rea_mcp_server() -> list[dict[str, Any]]:
    """Stdio MCP entry: npx -y rea-agents@PIN mcp (RFC-0200 launch table)."""
    pin = rea_package_pin()
    env = {
        "REA_INVESTIGATION_INPUT_ROOTS_JSON": mcp_investigation_roots_json(),
        **suppressed_dynamic_rea_envs(),
    }
    return [
        {
            "name": REA_MCP_SERVER_NAME,
            "id": REA_MCP_CATALOG_KEY,
            "preset": "rea",
            "catalog_key": REA_MCP_CATALOG_KEY,
            "enabled": True,
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", f"rea-agents@{pin}", "mcp"],
            "env": env,
        }
    ]


def _status_ok(status: dict[str, str]) -> bool:
    if not status:
        return False
    for value in status.values():
        if value.startswith("error:") or value == "disabled":
            continue
        if value:
            return True
    return False


def persist_rea_preset() -> None:
    ensure_mcp_preset("rea")


async def register_rea_mcp() -> McpRegistrationResult:
    """Refresh Jarvis MCP runtime with REA when the owner has enabled it."""
    global _MCP_STATUS, _MCP_LAST_ERROR
    settings = load_settings()
    if not settings.rea.enabled:
        _MCP_LAST_ERROR = "REA MCP is not enabled"
        _MCP_STATUS = {REA_MCP_SERVER_NAME: f"error: {_MCP_LAST_ERROR}"}
        return McpRegistrationResult(False, servers=_MCP_STATUS, error=_MCP_LAST_ERROR)

    persist_rea_preset()
    settings = load_settings()
    dynamic = build_rea_mcp_server()[0]
    base = [
        item
        for item in (settings.mcp_servers or [])
        if str(item.get("preset") or item.get("name") or "").strip().lower() != REA_MCP_SERVER_NAME
    ]
    merged = base + [dynamic]
    try:
        status = await MCP.refresh(merged)
    except Exception as exc:
        _MCP_LAST_ERROR = str(exc)[:400]
        _MCP_STATUS = {REA_MCP_SERVER_NAME: f"error: {_MCP_LAST_ERROR}"}
        log.debug("REA MCP refresh failed", exc_info=True)
        audit_security_event("rea.mcp_register_failed", error=_MCP_LAST_ERROR)
        return McpRegistrationResult(False, servers=_MCP_STATUS, error=_MCP_LAST_ERROR)

    _MCP_STATUS = status
    if not _status_ok(status):
        _MCP_LAST_ERROR = status.get(REA_MCP_SERVER_NAME) or "REA MCP list_tools did not succeed"
        audit_security_event("rea.mcp_register_failed", detail=status, error=_MCP_LAST_ERROR)
        return McpRegistrationResult(False, servers=status, error=_MCP_LAST_ERROR)

    _MCP_LAST_ERROR = ""
    audit_security_event("rea.mcp_registered", detail=status, catalog_key=REA_MCP_CATALOG_KEY)
    return McpRegistrationResult(True, servers=status, transport="stdio")


async def unregister_rea_mcp() -> None:
    global _MCP_STATUS, _MCP_LAST_ERROR
    settings = load_settings()
    base = [
        item
        for item in (settings.mcp_servers or [])
        if str(item.get("preset") or item.get("name") or "").strip().lower() != REA_MCP_SERVER_NAME
    ]
    try:
        await MCP.refresh(base)
    except Exception:
        log.debug("REA MCP unregister refresh failed", exc_info=True)
    _MCP_STATUS = {}
    _MCP_LAST_ERROR = ""
    audit_security_event("rea.mcp_unregistered")


def require_rea_permission(permission_id: str, *, action_kind: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Return a parked approval payload, or None when already allowed. Raises on deny."""
    from ..policy.approval_pending import park_action
    from ..policy.computer_permissions import evaluate_permission

    decision = evaluate_permission(permission_id)
    if decision.status == "deny":
        raise PermissionError(decision.reason)
    if decision.status != "ask":
        return None
    return park_action(action_kind=action_kind, permission_ids=[permission_id], context=context)


async def enable_rea_mcp(*, context: dict[str, Any] | None = None) -> dict[str, Any]:
    parked = require_rea_permission(
        REA_ENABLE_PERMISSION,
        action_kind="rea.enable_mcp",
        context=context or {},
    )
    if parked is not None:
        return parked
    settings = load_settings()
    settings.rea.enabled = True
    save_settings(settings)
    persist_rea_preset()
    result = await register_rea_mcp()
    return {"enabled": True, "registration": result.as_dict()}


def grant_investigation_root(root: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    parked = require_rea_permission(
        REA_NEW_ROOT_PERMISSION,
        action_kind="rea.grant_root",
        context={"root": root, **(context or {})},
    )
    if parked is not None:
        return parked
    from .rea_paths import intersect_roots, is_absolute_owner_path, jarvis_allowed_roots
    from ..tools.safety import reject_unsafe_path_text

    text = str(root or "").strip()
    if not is_absolute_owner_path(text):
        raise PermissionError("root must be an absolute path")
    reject_unsafe_path_text(text)

    allowed = jarvis_allowed_roots()
    intersecting = intersect_roots([text], allowed)
    if not intersecting:
        raise PermissionError("root is outside allowed_directories")
    resolved = intersecting[0]
    settings = load_settings()
    current = [str(item).strip() for item in (settings.rea.investigation_roots or []) if str(item).strip()]
    if resolved not in current:
        current.append(resolved)
        settings.rea.investigation_roots = current
        save_settings(settings)
    audit_security_event("rea.root_granted", root=resolved)
    return {"ok": True, "root": resolved, "investigation_roots": list(settings.rea.investigation_roots)}
