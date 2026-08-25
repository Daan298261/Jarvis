from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import NodeCapability
from ..db.session import SessionLocal
from ..hardware import hardware_dict
from ..tools.capabilities import native_capabilities
from .roles import ROLE_LEADER, ROLE_ORCHESTRATOR
from .workers import worker_catalog

ROLE_NAMES = frozenset({ROLE_ORCHESTRATOR, ROLE_LEADER})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _native_by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in native_capabilities() if item.get("id")}


def _workers_by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in worker_catalog() if item.get("id")}


def detect_localhost_capabilities() -> list[dict[str, Any]]:
    """Detect technical capabilities for localhost from hardware and worker probes."""
    hardware = hardware_dict()
    native = _native_by_id()
    workers = _workers_by_id()
    detected: list[dict[str, Any]] = []

    filesystem = native.get("filesystem", {})
    detected.append(
        {
            "id": "filesystem",
            "name": "Filesystem",
            "status": filesystem.get("status") or ("ready" if filesystem.get("available") else "unavailable"),
            "detail": str(filesystem.get("detail") or "Local filesystem access."),
        }
    )

    git = native.get("git", {})
    detected.append(
        {
            "id": "git",
            "name": "Git",
            "status": git.get("status") or ("ready" if git.get("available") else "missing"),
            "detail": str(git.get("detail") or "Git CLI availability."),
        }
    )

    docker = native.get("docker", {})
    detected.append(
        {
            "id": "docker",
            "name": "Docker",
            "status": docker.get("status")
            or ("ready" if hardware.get("docker_installed") or docker.get("available") else "unavailable"),
            "detail": str(docker.get("detail") or "Docker CLI availability."),
        }
    )

    gpu_ready = bool(hardware.get("gpu_name"))
    detected.append(
        {
            "id": "gpu",
            "name": "GPU",
            "status": "ready" if gpu_ready else "unavailable",
            "detail": (
                f"GPU: {hardware.get('gpu_name')}"
                if gpu_ready
                else "No NVIDIA GPU detected on this node."
            ),
        }
    )

    llm = workers.get("local-llm", {})
    detected.append(
        {
            "id": "llm_inference",
            "name": "LLM Inference",
            "status": str(llm.get("status") or "unknown"),
            "detail": "Local llama.cpp inference worker.",
        }
    )

    playwright = native.get("playwright", {})
    browser_use = workers.get("browser-use", {})
    browser_ready = bool(playwright.get("available")) or browser_use.get("status") == "ready"
    detected.append(
        {
            "id": "browser",
            "name": "Browser Automation",
            "status": "ready" if browser_ready else "unavailable",
            "detail": (
                "Playwright and/or Browser Use worker available."
                if browser_ready
                else "Install Playwright or configure Browser Use."
            ),
        }
    )

    desktop = native.get("windows_ui", {})
    detected.append(
        {
            "id": "desktop_control",
            "name": "Desktop Control",
            "status": desktop.get("status") or ("ready" if desktop.get("available") else "unavailable"),
            "detail": str(desktop.get("detail") or "Windows UI Automation / desktop control."),
        }
    )

    coding_workers = [item for item in workers.values() if item.get("kind") == "coding"]
    coding_ready = any(item.get("status") in {"ready", "not_loaded", "unknown"} for item in coding_workers)
    detected.append(
        {
            "id": "coding",
            "name": "Coding Workers",
            "status": "ready" if coding_ready else "unavailable",
            "detail": (
                f"{len(coding_workers)} coding worker(s) cataloged on this node."
                if coding_workers
                else "No coding workers available."
            ),
        }
    )

    core_tools = [native.get(key, {}) for key in ("filesystem", "terminal", "python")]
    tool_ready = all(item.get("available") for item in core_tools)
    detected.append(
        {
            "id": "tool_execution",
            "name": "Tool Execution",
            "status": "ready" if tool_ready else "unavailable",
            "detail": "Core Jarvis native tool execution (filesystem, shell, python).",
        }
    )

    voice = workers.get("voice") or native.get("voice", {})
    detected.append(
        {
            "id": "voice",
            "name": "Voice",
            "status": voice.get("status") or ("ready" if voice.get("available") else "missing"),
            "detail": str(voice.get("detail") or "Local STT/TTS availability."),
        }
    )

    for item in detected:
        cap_id = str(item["id"])
        if cap_id in ROLE_NAMES:
            raise ValueError(f"Capability id must not be a role name: {cap_id}")

    return detected


def capability_to_dict(binding: NodeCapability) -> dict[str, Any]:
    return {
        "id": binding.capability_id,
        "name": binding.name,
        "status": binding.status,
        "detail": binding.detail,
        "node_id": binding.node_id,
    }


async def register_localhost_capabilities(node_id: str) -> list[dict[str, Any]]:
    """Bind detected localhost capabilities to a Node. Idempotent across restarts."""
    catalog = detect_localhost_capabilities()
    catalog_ids = {item["id"] for item in catalog}
    now = _utcnow()

    async with SessionLocal() as session:
        existing = (
            await session.execute(select(NodeCapability).where(NodeCapability.node_id == node_id))
        ).scalars().all()
        by_capability_id = {row.capability_id: row for row in existing}

        for item in catalog:
            capability_id = item["id"]
            row = by_capability_id.get(capability_id)
            if row is None:
                session.add(
                    NodeCapability(
                        node_id=node_id,
                        capability_id=capability_id,
                        name=item["name"],
                        status=item["status"],
                        detail=item["detail"],
                        updated_at=now,
                    )
                )
                continue
            row.name = item["name"]
            row.status = item["status"]
            row.detail = item["detail"]
            row.updated_at = now

        for row in existing:
            if row.capability_id not in catalog_ids:
                await session.delete(row)

        await session.commit()
        rows = (
            await session.execute(
                select(NodeCapability)
                .where(NodeCapability.node_id == node_id)
                .order_by(NodeCapability.capability_id.asc())
            )
        ).scalars().all()
        return [capability_to_dict(row) for row in rows]


async def list_node_capabilities(node_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(NodeCapability)
                .where(NodeCapability.node_id == node_id)
                .order_by(NodeCapability.capability_id.asc())
            )
        ).scalars().all()
        return [capability_to_dict(row) for row in rows]


async def list_all_capabilities() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(NodeCapability).order_by(
                    NodeCapability.node_id.asc(),
                    NodeCapability.capability_id.asc(),
                )
            )
        ).scalars().all()
        return [capability_to_dict(row) for row in rows]
