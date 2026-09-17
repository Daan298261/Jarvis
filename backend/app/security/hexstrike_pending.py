"""Resume parked HexStrike API actions after owner approval (RFC-0110)."""
from __future__ import annotations

from typing import Any

from ..policy.computer_permissions import consume_once_grants
from .hexstrike import HEXSTRIKE
from .hexstrike_defensive import execute_defensive, stop_managed_job, upsert_scope
from .hexstrike_install import HEXSTRIKE_INSTALLER
from .hexstrike_operator import operate, stop_operator_job, sync_operator_surface
from .hexstrike_tools import (
    install_all_missing,
    install_host_tool,
    missing_host_tools,
    start_dependency_install,
)


async def execute_parked_hexstrike_action(
    action_kind: str,
    context: dict[str, Any],
    *,
    decision: str = "",
) -> dict[str, Any]:
    kind = (action_kind or "").strip().lower()
    permission_ids = list(context.get("_permission_ids") or [])
    normalized_decision = str(decision or "").strip().lower()
    payload: dict[str, Any]

    if kind == "hexstrike.start":
        payload = (await HEXSTRIKE.ensure_started()).as_dict()
    elif kind == "hexstrike.stop_install":
        payload = (await HEXSTRIKE_INSTALLER.cancel()).as_dict()
    elif kind == "hexstrike.install":
        path = context.get("install_path")
        payload = HEXSTRIKE_INSTALLER.start(path).as_dict()
    elif kind == "hexstrike.dependencies.install":
        tool = context.get("tool")
        if tool:
            result = await install_host_tool(str(tool))
            payload = result.as_dict()
        else:
            missing_before = missing_host_tools()
            results = await install_all_missing()
            payload = {
                "missing_before": missing_before,
                "results": [item.as_dict() for item in results],
            }
    elif kind == "hexstrike.tool.install":
        tool_id = str(context.get("tool_id") or "")
        install_path = str(context.get("install_path") or "")
        payload = start_dependency_install(tool_id, install_path=install_path)
    elif kind == "hexstrike.tools.refresh":
        surface = await sync_operator_surface(register_mcp=True)
        if not surface.get("operator_ready"):
            raise RuntimeError(surface.get("mcp", {}).get("error") or "HexStrike operator surface is not ready")
        from .hexstrike_operator import catalog_snapshot, discovered_catalog

        payload = {
            "catalog": discovered_catalog(),
            "count": surface.get("catalog_count"),
            "operator": surface,
            **catalog_snapshot(),
        }
    elif kind == "hexstrike.operate":
        capability_id = str(context.get("capability_id") or "")
        arguments = context.get("arguments") or {}
        payload = await operate(capability_id, arguments)
    elif kind == "hexstrike.job.stop":
        payload = await stop_operator_job(str(context.get("job_id") or ""))
    elif kind == "hexstrike.defensive.action":
        payload = await execute_defensive(
            str(context.get("action") or ""),
            str(context.get("scope_id") or ""),
            dict(context.get("options") or {}),
        )
    elif kind == "hexstrike.defensive.stop":
        payload = await stop_managed_job(str(context.get("job_id") or ""))
    elif kind == "hexstrike.scope.put":
        payload = upsert_scope(
            str(context.get("scope_id") or ""),
            kind=str(context.get("kind") or ""),
            value=str(context.get("value") or ""),
            label=str(context.get("label") or ""),
            attested_owned=bool(context.get("attested_owned")),
        )
    else:
        raise ValueError(f"Unknown parked HexStrike action: {action_kind}")

    if normalized_decision == "allow_once" and permission_ids:
        consume_once_grants(permission_ids)
    return payload
