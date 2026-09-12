"""Computer-use targeting: this device vs worker nodes, plus RDP (RFC-0079)."""
from __future__ import annotations

from typing import Any

from ..policy.computer_permissions import (
    blue_isolate_playbook,
    evaluate_permission,
    operator_intent_grant,
)
from ..swarm.nodes import list_nodes
from ..workers.computer import CuaBackend, UFOBackend
from ..workers.remote_desktop import launch_rdp, validate_rdp_host


def _capability_ids(node: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in node.get("capabilities") or []:
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
        elif isinstance(item, str):
            ids.add(item)
    return ids


def _desktop_ready(node: dict[str, Any]) -> bool:
    for item in node.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        if item.get("id") != "desktop_control":
            continue
        status = str(item.get("status") or "").lower()
        return status in {"ready", "available", "ok"}
    return "desktop_control" in _capability_ids(node)


async def list_computer_targets() -> list[dict[str, Any]]:
    nodes = await list_nodes()
    targets: list[dict[str, Any]] = []
    for node in nodes:
        desktop = _desktop_ready(node)
        is_local = bool(node.get("is_local"))
        address = str(node.get("address") or node.get("host_alias") or "")
        hostname = str(node.get("hostname") or "")
        targets.append(
            {
                "node_id": node.get("id"),
                "hostname": hostname,
                "address": address,
                "is_local": is_local,
                "kind": "this_device" if is_local else "worker_node",
                "desktop_control": desktop,
                "status": node.get("status"),
                "rdp_host": None if is_local else (address or hostname),
            }
        )
    return targets


def _local_backends() -> dict[str, Any]:
    ufo = UFOBackend()
    cua = CuaBackend()
    return {
        "ufo": ufo.probe(),
        "cua": cua.probe(),
        "native_desktop": {"id": "desktop", "available": True, "detail": "Native desktop tool on this process."},
    }


async def plan_computer_use(
    goal: str,
    *,
    preferred_node_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    text = (goal or "").strip()
    if not text:
        raise ValueError("goal is required")
    this_device = evaluate_permission("computer.this_device")
    workers = evaluate_permission("computer.worker_nodes")
    rdp = evaluate_permission("computer.rdp")
    targets = await list_computer_targets()
    preferred = (preferred_node_id or "").strip()
    chosen = None
    if preferred:
        chosen = next((item for item in targets if item.get("node_id") == preferred), None)
    if chosen is None:
        local_ready = next((item for item in targets if item.get("is_local") and item.get("desktop_control")), None)
        remote_ready = next((item for item in targets if not item.get("is_local") and item.get("desktop_control")), None)
        if this_device.allowed and local_ready:
            chosen = local_ready
        elif workers.allowed and remote_ready:
            chosen = remote_ready
        else:
            chosen = local_ready or remote_ready or (targets[0] if targets else None)

    steps: list[str] = [
        "Phone or companion sends the request to the Jarvis leader.",
        "Leader classifies the work as computer use and selects a node with desktop_control.",
    ]
    rdp_plan: dict[str, Any] | None = None
    if chosen and not chosen.get("is_local"):
        steps.append("Worker node will own the GUI session (native desktop / UFO / Cua on that host).")
        host = chosen.get("rdp_host")
        if host:
            steps.append(
                "If Remote Desktop is permitted, the leader opens mstsc to that node so Jarvis can drive the session."
            )
            rdp_plan = {
                "host": host,
                "permission": rdp.status,
                "command": ["mstsc", f"/v:{host}"],
            }
    else:
        steps.append("Run native desktop / UFO / Cua on this device.")

    pending = [item.permission_id for item in (this_device, workers, rdp) if item.status == "ask"]
    return {
        "goal": text,
        "source": source or "unspecified",
        "target": chosen,
        "targets": targets,
        "permissions": {
            "computer.this_device": this_device.status,
            "computer.worker_nodes": workers.status,
            "computer.rdp": rdp.status,
        },
        "pending": pending,
        "local_backends": _local_backends(),
        "rdp": rdp_plan,
        "steps": steps,
        "note": (
            "Computer-use tools execute on the selected node. RDP is a local client launch "
            "from the leader, not a new remote protocol."
        ),
    }


async def start_rdp_session(*, host: str | None = None, node_id: str | None = None) -> dict[str, Any]:
    decision = evaluate_permission("computer.rdp")
    if decision.status == "ask":
        operator_intent_grant("computer.rdp", "allow_session")
        decision = evaluate_permission("computer.rdp")
    if decision.status != "allow":
        raise PermissionError(decision.reason)
    workers = evaluate_permission("computer.worker_nodes")
    if workers.status == "ask":
        operator_intent_grant("computer.worker_nodes", "allow_session")
        workers = evaluate_permission("computer.worker_nodes")
    if workers.status == "deny":
        raise PermissionError(workers.reason)
    target_host = host
    matched = None
    if node_id:
        for item in await list_computer_targets():
            if item.get("node_id") == node_id:
                matched = item
                target_host = target_host or item.get("rdp_host")
                break
        if matched is None:
            raise KeyError(node_id)
        if matched.get("is_local"):
            raise ValueError("This device does not need RDP; computer use runs locally.")
    if not target_host:
        raise ValueError("RDP host or worker node_id is required")
    result = launch_rdp(validate_rdp_host(str(target_host)))
    result["permission"] = decision.status
    result["node_id"] = node_id
    return result


def isolate_device_plan(*, device: str, reason: str = "") -> dict[str, Any]:
    return blue_isolate_playbook(device=device, reason=reason)
