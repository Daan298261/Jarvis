from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import (
    ContextFact,
    ContextFactConflict,
    ContextFactIndex,
    ContextFactPermission,
    ContextFactProvenance,
    ContextMutation,
    ContextRepository,
    utcnow,
)
from ..db.session import SessionLocal
from .schema import ContextEntry, EntryProvenance, MutationRecord

_NORMALIZE_RE = re.compile(r"\s+")
_DEFAULT_PERMISSIONS = ("read", "write", "delete", "pin")


def _normalize_key(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", (text or "").strip().lower())


def _content_hash(content: str) -> str:
    payload = _normalize_key(content)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    return dt.isoformat()


def _provenance_from_row(row: ContextFactProvenance) -> EntryProvenance:
    return EntryProvenance(
        source_type=row.source_type,
        source_id=row.source_id or None,
        trajectory_id=row.trajectory_id or None,
        mutation_id=row.mutation_id or None,
        note=row.note or None,
        created_at=_iso(row.created_at),
    )


async def _conflict_ids(session, agent_id: str, fact_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(ContextFactConflict).where(
                ContextFactConflict.agent_id == agent_id,
                ContextFactConflict.resolved.is_(False),
            )
        )
    ).scalars().all()
    conflicts: list[str] = []
    for row in rows:
        if row.fact_id_a == fact_id:
            conflicts.append(row.fact_id_b)
        elif row.fact_id_b == fact_id:
            conflicts.append(row.fact_id_a)
    return sorted(set(conflicts))


async def fact_to_entry(session, row: ContextFact) -> ContextEntry:
    provenance_row = (
        await session.execute(
            select(ContextFactProvenance)
            .where(ContextFactProvenance.fact_id == row.id)
            .order_by(ContextFactProvenance.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    provenance = _provenance_from_row(provenance_row) if provenance_row else EntryProvenance(
        source_type="unknown",
        created_at=_iso(row.created_at),
    )
    metadata: dict[str, Any] = {}
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except Exception:
        metadata = {}
    return ContextEntry(
        id=row.id,
        category=row.category,
        title=row.title,
        content=row.content,
        pinned=row.pinned,
        active=row.active,
        conflicts_with=await _conflict_ids(session, row.agent_id, row.id),
        provenance=provenance,
        superseded_by=row.superseded_by,
        metadata=metadata,
    )


async def ensure_repository(agent_id: str) -> ContextRepository:
    async with SessionLocal() as session:
        repo = await session.get(ContextRepository, agent_id)
        if repo is not None:
            return repo
        now = utcnow()
        repo = ContextRepository(agent_id=agent_id, current_version=1, created_at=now, updated_at=now)
        session.add(repo)
        await session.commit()
        await session.refresh(repo)
        return repo


async def load_active_facts(agent_id: str) -> list[ContextEntry]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ContextFact)
                .where(ContextFact.agent_id == agent_id, ContextFact.active.is_(True))
                .order_by(ContextFact.created_at.asc())
            )
        ).scalars().all()
        return [await fact_to_entry(session, row) for row in rows]


async def get_fact_row(agent_id: str, fact_id: str) -> ContextFact | None:
    async with SessionLocal() as session:
        row = await session.get(ContextFact, fact_id)
        if row is None or row.agent_id != agent_id:
            return None
        return row


async def find_duplicate(
    agent_id: str,
    *,
    category: str,
    title: str,
    content: str,
) -> ContextFact | None:
    title_key = _normalize_key(title)
    content_hash = _content_hash(content)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ContextFact).where(
                    ContextFact.agent_id == agent_id,
                    ContextFact.active.is_(True),
                    ContextFact.category == category,
                    ContextFact.title_key == title_key,
                    ContextFact.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        return row


async def detect_conflicts(
    agent_id: str,
    *,
    category: str,
    title: str,
    content: str,
    exclude_id: str | None = None,
) -> list[str]:
    title_key = _normalize_key(title)
    content_hash = _content_hash(content)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ContextFact).where(
                    ContextFact.agent_id == agent_id,
                    ContextFact.active.is_(True),
                    ContextFact.category == category,
                    ContextFact.title_key == title_key,
                )
            )
        ).scalars().all()
        conflicts: list[str] = []
        for row in rows:
            if exclude_id and row.id == exclude_id:
                continue
            if row.content_hash != content_hash:
                conflicts.append(row.id)
        return conflicts


async def record_conflict(agent_id: str, fact_id_a: str, fact_id_b: str, *, reason: str) -> None:
    if fact_id_a == fact_id_b:
        return
    ordered = sorted((fact_id_a, fact_id_b))
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(ContextFactConflict).where(
                    ContextFactConflict.agent_id == agent_id,
                    ContextFactConflict.fact_id_a == ordered[0],
                    ContextFactConflict.fact_id_b == ordered[1],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            ContextFactConflict(
                agent_id=agent_id,
                fact_id_a=ordered[0],
                fact_id_b=ordered[1],
                reason=reason,
            )
        )
        await session.commit()


async def create_fact_indexes(
    session,
    *,
    agent_id: str,
    fact_id: str,
    category: str,
    title: str,
    content: str,
) -> None:
    title_key = _normalize_key(title)
    content_hash = _content_hash(content)
    for kind, key, value in (
        ("title", title_key, title),
        ("category", category, category),
        ("content_hash", content_hash, content_hash),
    ):
        session.add(
            ContextFactIndex(
                agent_id=agent_id,
                fact_id=fact_id,
                index_kind=kind,
                index_key=key,
                index_value=value[:1000],
            )
        )


async def grant_default_permissions(session, *, agent_id: str, fact_id: str) -> None:
    for permission in _DEFAULT_PERMISSIONS:
        session.add(
            ContextFactPermission(
                fact_id=fact_id,
                agent_id=agent_id,
                principal_type="agent",
                principal_id=agent_id,
                permission=permission,
            )
        )


async def persist_mutation(record: MutationRecord) -> None:
    async with SessionLocal() as session:
        session.add(
            ContextMutation(
                mutation_id=record.mutation_id,
                agent_id=record.agent_id,
                version_before=record.version_before,
                version_after=record.version_after,
                action=record.action,
                fact_id=record.entry_id,
                source_json=json.dumps(record.source.model_dump(mode="json")),
                before_json=json.dumps(record.before.model_dump(mode="json")) if record.before else "",
                after_json=json.dumps(record.after.model_dump(mode="json")) if record.after else "",
                reversible=record.reversible,
                reverted_by=record.reverted_by,
                created_at=utcnow(),
            )
        )
        await session.commit()


async def get_mutation(agent_id: str, mutation_id: str) -> MutationRecord | None:
    async with SessionLocal() as session:
        row = await session.get(ContextMutation, mutation_id)
        if row is None or row.agent_id != agent_id:
            return None
        source = EntryProvenance.model_validate(json.loads(row.source_json or "{}"))
        before = ContextEntry.model_validate(json.loads(row.before_json)) if row.before_json else None
        after = ContextEntry.model_validate(json.loads(row.after_json)) if row.after_json else None
        return MutationRecord(
            mutation_id=row.mutation_id,
            agent_id=row.agent_id,
            version_before=row.version_before,
            version_after=row.version_after,
            action=row.action,
            entry_id=row.fact_id,
            source=source,
            before=before,
            after=after,
            reversible=row.reversible,
            reverted_by=row.reverted_by,
            created_at=_iso(row.created_at),
        )


async def list_mutations(agent_id: str, *, limit: int = 100) -> list[MutationRecord]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ContextMutation)
                .where(ContextMutation.agent_id == agent_id)
                .order_by(ContextMutation.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).scalars().all()
        items: list[MutationRecord] = []
        for row in rows:
            source = EntryProvenance.model_validate(json.loads(row.source_json or "{}"))
            before = ContextEntry.model_validate(json.loads(row.before_json)) if row.before_json else None
            after = ContextEntry.model_validate(json.loads(row.after_json)) if row.after_json else None
            items.append(
                MutationRecord(
                    mutation_id=row.mutation_id,
                    agent_id=row.agent_id,
                    version_before=row.version_before,
                    version_after=row.version_after,
                    action=row.action,
                    entry_id=row.fact_id,
                    source=source,
                    before=before,
                    after=after,
                    reversible=row.reversible,
                    reverted_by=row.reverted_by,
                    created_at=_iso(row.created_at),
                )
            )
        return list(reversed(items))


async def mark_mutation_reverted(agent_id: str, mutation_id: str, *, reverted_by: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(ContextMutation, mutation_id)
        if row is None or row.agent_id != agent_id:
            return
        row.reverted_by = reverted_by
        await session.commit()


async def bump_repository_version(agent_id: str, next_version: int) -> None:
    async with SessionLocal() as session:
        repo = await session.get(ContextRepository, agent_id)
        if repo is None:
            return
        repo.current_version = next_version
        repo.updated_at = utcnow()
        await session.commit()


async def get_repository_version(agent_id: str) -> int:
    repo = await ensure_repository(agent_id)
    return repo.current_version


async def save_fact(
    *,
    agent_id: str,
    entry: ContextEntry,
    repo_version: int,
    provenance: EntryProvenance,
    conflicts: list[str],
) -> ContextFact:
    async with SessionLocal() as session:
        row = ContextFact(
            id=entry.id,
            agent_id=agent_id,
            category=entry.category,
            title=entry.title,
            content=entry.content,
            title_key=_normalize_key(entry.title),
            content_hash=_content_hash(entry.content),
            pinned=entry.pinned,
            active=entry.active,
            repo_version=repo_version,
            superseded_by=entry.superseded_by,
            metadata_json=json.dumps(entry.metadata or {}),
        )
        session.add(row)
        session.add(
            ContextFactProvenance(
                fact_id=entry.id,
                agent_id=agent_id,
                source_type=provenance.source_type,
                source_id=provenance.source_id or "",
                trajectory_id=provenance.trajectory_id or "",
                mutation_id=provenance.mutation_id or "",
                note=provenance.note or "",
            )
        )
        await create_fact_indexes(
            session,
            agent_id=agent_id,
            fact_id=entry.id,
            category=entry.category,
            title=entry.title,
            content=entry.content,
        )
        await grant_default_permissions(session, agent_id=agent_id, fact_id=entry.id)
        for conflict_id in conflicts:
            ordered = sorted((entry.id, conflict_id))
            existing = (
                await session.execute(
                    select(ContextFactConflict).where(
                        ContextFactConflict.agent_id == agent_id,
                        ContextFactConflict.fact_id_a == ordered[0],
                        ContextFactConflict.fact_id_b == ordered[1],
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    ContextFactConflict(
                        agent_id=agent_id,
                        fact_id_a=ordered[0],
                        fact_id_b=ordered[1],
                        reason="conflicting_evidence",
                    )
                )
        await session.commit()
        return row


async def update_fact(agent_id: str, entry: ContextEntry, *, repo_version: int) -> None:
    async with SessionLocal() as session:
        row = await session.get(ContextFact, entry.id)
        if row is None or row.agent_id != agent_id:
            raise ValueError("Fact not found")
        row.category = entry.category
        row.title = entry.title
        row.content = entry.content
        row.title_key = _normalize_key(entry.title)
        row.content_hash = _content_hash(entry.content)
        row.pinned = entry.pinned
        row.active = entry.active
        row.repo_version = repo_version
        row.superseded_by = entry.superseded_by
        row.metadata_json = json.dumps(entry.metadata or {})
        row.updated_at = utcnow()
        await session.commit()


async def list_permissions(agent_id: str, fact_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ContextFactPermission).where(
                    ContextFactPermission.agent_id == agent_id,
                    ContextFactPermission.fact_id == fact_id,
                )
            )
        ).scalars().all()
        return [
            {
                "principal_type": row.principal_type,
                "principal_id": row.principal_id,
                "permission": row.permission,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]


def new_entry_id() -> str:
    return str(uuid.uuid4())


def new_mutation_id() -> str:
    return str(uuid.uuid4())
