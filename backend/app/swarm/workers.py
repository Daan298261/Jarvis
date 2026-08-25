from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import NodeWorker
from ..db.session import SessionLocal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def worker_catalog() -> list[dict[str, Any]]:
    """Collect software Workers available on this machine (distinct from Nodes)."""
    from ..agent.acp import acp_status
    from ..agent.coding_workers import coding_worker_catalog
    from ..inference.manager import MANAGER
    from ..tools.capabilities import native_capabilities
    from ..workers.browser import BrowserUseBackend
    from ..workers.code import OpenHandsBackend
    from ..workers.computer import CuaBackend, UFOBackend
    from ..workers.interpreter import OpenInterpreterBackend
    from ..workers.voice import voice_status

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any], *, kind: str | None = None) -> None:
        worker_id = str(item.get("id") or "").strip()
        if not worker_id or worker_id in seen:
            return
        seen.add(worker_id)
        entries.append(
            {
                "id": worker_id,
                "name": str(item.get("name") or worker_id),
                "kind": kind or str(item.get("kind") or "worker"),
                "status": str(item.get("status") or "unknown"),
            }
        )

    for backend in (
        BrowserUseBackend(),
        UFOBackend(),
        CuaBackend(),
        OpenHandsBackend(),
        OpenInterpreterBackend(),
    ):
        add(backend.probe())

    for cap in native_capabilities():
        add(cap)

    for worker in coding_worker_catalog():
        add({**worker, "kind": "coding"}, kind="coding")

    acp = acp_status()
    add(
        {
            "id": acp.get("id") or "cursor-acp",
            "name": acp.get("name") or "Cursor ACP",
            "status": acp.get("status") or "unknown",
        },
        kind="coding",
    )

    add(voice_status())

    llm_status = "ready" if MANAGER.state.loaded else "not_loaded"
    if MANAGER.state.last_error and not MANAGER.state.loaded:
        llm_status = "error"
    add(
        {
            "id": "local-llm",
            "name": "Local LLM",
            "status": llm_status,
        },
        kind="inference",
    )

    return entries


def worker_binding_to_dict(binding: NodeWorker) -> dict[str, Any]:
    return {
        "id": binding.worker_id,
        "name": binding.name,
        "kind": binding.kind,
        "status": binding.status,
        "node_id": binding.node_id,
    }


async def bind_workers_to_node(node_id: str) -> list[dict[str, Any]]:
    """Attach the current worker catalog to a Node. Idempotent across restarts."""
    catalog = worker_catalog()
    catalog_ids = {item["id"] for item in catalog}
    now = _utcnow()

    async with SessionLocal() as session:
        existing = (
            await session.execute(select(NodeWorker).where(NodeWorker.node_id == node_id))
        ).scalars().all()
        by_worker_id = {row.worker_id: row for row in existing}

        for item in catalog:
            worker_id = item["id"]
            row = by_worker_id.get(worker_id)
            if row is None:
                session.add(
                    NodeWorker(
                        node_id=node_id,
                        worker_id=worker_id,
                        name=item["name"],
                        kind=item["kind"],
                        status=item["status"],
                        updated_at=now,
                    )
                )
                continue
            row.name = item["name"]
            row.kind = item["kind"]
            row.status = item["status"]
            row.updated_at = now

        for row in existing:
            if row.worker_id not in catalog_ids:
                await session.delete(row)

        await session.commit()
        rows = (
            await session.execute(
                select(NodeWorker)
                .where(NodeWorker.node_id == node_id)
                .order_by(NodeWorker.worker_id.asc())
            )
        ).scalars().all()
        return [worker_binding_to_dict(row) for row in rows]


async def list_node_workers(node_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(NodeWorker)
                .where(NodeWorker.node_id == node_id)
                .order_by(NodeWorker.worker_id.asc())
            )
        ).scalars().all()
        return [worker_binding_to_dict(row) for row in rows]
