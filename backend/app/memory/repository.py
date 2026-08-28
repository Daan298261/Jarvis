from __future__ import annotations

from typing import Any

from .db_layer import (
    bump_repository_version,
    detect_conflicts,
    ensure_repository,
    fact_to_entry,
    find_duplicate,
    get_mutation,
    get_repository_version,
    list_mutations,
    list_permissions,
    load_active_facts,
    mark_mutation_reverted,
    new_entry_id,
    new_mutation_id,
    persist_mutation,
    save_fact,
    update_fact,
)
from .schema import (
    ContextEntry,
    ContextRepoVersion,
    EntryProvenance,
    MutationRecord,
    VersionDiff,
)
from .store import (
    ensure_initial_repo,
    list_version_numbers,
    load_version,
    save_meta,
    save_version,
    _utc_now,
)
from ..db.session import SessionLocal
from ..db.models import ContextFact
from ..config import data_dir


class ContextRepoError(ValueError):
    pass


async def _build_repo_version(agent_id: str, version: int | None = None) -> ContextRepoVersion:
    await ensure_repository(agent_id)
    current = version if version is not None else await get_repository_version(agent_id)
    entries = await load_active_facts(agent_id)
    meta = ensure_initial_repo(agent_id)
    return ContextRepoVersion(
        agent_id=agent_id,
        version=current,
        created_at=meta.created_at,
        parent_version=current - 1 if current > 1 else None,
        entries=entries,
    )


async def _snapshot_version(agent_id: str, repo: ContextRepoVersion, mutation: MutationRecord) -> ContextRepoVersion:
    save_version(repo)
    from .store import load_meta

    meta = load_meta(agent_id)
    if meta is not None:
        save_meta(meta.model_copy(update={"current_version": repo.version, "updated_at": repo.created_at}))
    await bump_repository_version(agent_id, repo.version)
    await persist_mutation(mutation)
    return repo


async def get_repo(agent_id: str) -> ContextRepoVersion:
    ensure_initial_repo(agent_id)
    return await _build_repo_version(agent_id)


async def get_version(agent_id: str, version: int) -> ContextRepoVersion | None:
    snapshot = load_version(agent_id, version)
    if snapshot is not None:
        return snapshot
    current = await get_repository_version(agent_id)
    if version == current:
        return await _build_repo_version(agent_id, version)
    return None


async def list_versions(agent_id: str) -> list[dict[str, Any]]:
    ensure_initial_repo(agent_id)
    await ensure_repository(agent_id)
    numbers = list_version_numbers(agent_id)
    items: list[dict[str, Any]] = []
    for number in numbers:
        repo = load_version(agent_id, number)
        if repo is None:
            continue
        items.append(
            {
                "version": repo.version,
                "created_at": repo.created_at,
                "parent_version": repo.parent_version,
                "entry_count": len([entry for entry in repo.entries if entry.active]),
            }
        )
    return items


async def list_history(agent_id: str, *, limit: int = 100) -> list[MutationRecord]:
    ensure_initial_repo(agent_id)
    return await list_mutations(agent_id, limit=limit)


async def get_entry(agent_id: str, entry_id: str) -> ContextEntry | None:
    async with SessionLocal() as session:
        row = await session.get(ContextFact, entry_id)
        if row is None or row.agent_id != agent_id or not row.active:
            return None
        return await fact_to_entry(session, row)


async def diff_versions(agent_id: str, from_version: int, to_version: int) -> VersionDiff:
    left = await get_version(agent_id, from_version)
    right = await get_version(agent_id, to_version)
    if left is None or right is None:
        raise ContextRepoError("One or both versions do not exist")

    left_map = {entry.id: entry for entry in left.entries if entry.active}
    right_map = {entry.id: entry for entry in right.entries if entry.active}

    added = [entry for entry_id, entry in right_map.items() if entry_id not in left_map]
    removed = [entry for entry_id, entry in left_map.items() if entry_id not in right_map]
    changed: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for entry_id in left_map.keys() & right_map.keys():
        before = left_map[entry_id]
        after = right_map[entry_id]
        if before.model_dump(mode="json") != after.model_dump(mode="json"):
            changed.append({"before": before, "after": after})
        if after.conflicts_with:
            conflicts.extend(after.conflicts_with)

    return VersionDiff(
        agent_id=agent_id,
        from_version=from_version,
        to_version=to_version,
        added=added,
        removed=removed,
        changed=changed,
        conflicts_flagged=sorted(set(conflicts)),
    )


async def add_entry(
    agent_id: str,
    *,
    category: str,
    title: str,
    content: str,
    source_type: str = "manual",
    source_id: str | None = None,
    trajectory_id: str | None = None,
    note: str | None = None,
    allow_duplicate: bool = False,
) -> tuple[ContextEntry, ContextRepoVersion, MutationRecord]:
    if category not in {
        "identity",
        "projects",
        "procedures",
        "lessons",
        "priorities",
        "skills",
    }:
        raise ContextRepoError(f"Unsupported category: {category}")

    ensure_initial_repo(agent_id)
    await ensure_repository(agent_id)
    parent_version = await get_repository_version(agent_id)

    if not allow_duplicate:
        duplicate = await find_duplicate(agent_id, category=category, title=title, content=content)
        if duplicate is not None:
            raise ContextRepoError("Duplicate entry already exists")

    now = _utc_now()
    mutation_id = new_mutation_id()
    provenance = EntryProvenance(
        source_type=source_type,
        source_id=source_id,
        trajectory_id=trajectory_id,
        mutation_id=mutation_id,
        note=note,
        created_at=now,
    )
    conflicts = await detect_conflicts(agent_id, category=category, title=title, content=content)
    entry = ContextEntry(
        id=new_entry_id(),
        category=category,
        title=title.strip(),
        content=content.strip(),
        provenance=provenance,
        conflicts_with=conflicts,
    )

    next_version = parent_version + 1
    await save_fact(
        agent_id=agent_id,
        entry=entry,
        repo_version=next_version,
        provenance=provenance,
        conflicts=conflicts,
    )

    mutation = MutationRecord(
        mutation_id=mutation_id,
        agent_id=agent_id,
        version_before=parent_version,
        version_after=next_version,
        action="create",
        entry_id=entry.id,
        source=provenance,
        before=None,
        after=entry,
        created_at=now,
    )
    repo = ContextRepoVersion(
        agent_id=agent_id,
        version=next_version,
        created_at=now,
        parent_version=parent_version,
        entries=await load_active_facts(agent_id),
    )
    await _snapshot_version(agent_id, repo, mutation)
    return entry, repo, mutation


async def pin_entry(agent_id: str, entry_id: str, *, pinned: bool = True) -> ContextEntry:
    entry = await get_entry(agent_id, entry_id)
    if entry is None:
        raise ContextRepoError("Entry not found")
    if entry.pinned == pinned:
        return entry

    parent_version = await get_repository_version(agent_id)
    now = _utc_now()
    mutation_id = new_mutation_id()
    provenance = EntryProvenance(
        source_type="manual",
        mutation_id=mutation_id,
        note="pin" if pinned else "unpin",
        created_at=now,
    )
    updated = entry.model_copy(update={"pinned": pinned})
    next_version = parent_version + 1
    await update_fact(agent_id, updated, repo_version=next_version)

    mutation = MutationRecord(
        mutation_id=mutation_id,
        agent_id=agent_id,
        version_before=parent_version,
        version_after=next_version,
        action="pin" if pinned else "unpin",
        entry_id=entry_id,
        source=provenance,
        before=entry,
        after=updated,
        created_at=now,
    )
    repo = ContextRepoVersion(
        agent_id=agent_id,
        version=next_version,
        created_at=now,
        parent_version=parent_version,
        entries=await load_active_facts(agent_id),
    )
    await _snapshot_version(agent_id, repo, mutation)
    return updated


async def delete_entry(agent_id: str, entry_id: str) -> ContextEntry:
    entry = await get_entry(agent_id, entry_id)
    if entry is None:
        raise ContextRepoError("Entry not found")
    if entry.pinned:
        raise ContextRepoError("Pinned entries cannot be deleted")

    parent_version = await get_repository_version(agent_id)
    now = _utc_now()
    mutation_id = new_mutation_id()
    provenance = EntryProvenance(
        source_type="manual",
        mutation_id=mutation_id,
        note="delete",
        created_at=now,
    )
    updated = entry.model_copy(update={"active": False})
    next_version = parent_version + 1
    await update_fact(agent_id, updated, repo_version=next_version)

    mutation = MutationRecord(
        mutation_id=mutation_id,
        agent_id=agent_id,
        version_before=parent_version,
        version_after=next_version,
        action="delete",
        entry_id=entry_id,
        source=provenance,
        before=entry,
        after=updated,
        created_at=now,
    )
    repo = ContextRepoVersion(
        agent_id=agent_id,
        version=next_version,
        created_at=now,
        parent_version=parent_version,
        entries=await load_active_facts(agent_id),
    )
    await _snapshot_version(agent_id, repo, mutation)
    return updated


async def revert_mutation(agent_id: str, mutation_id: str) -> ContextRepoVersion:
    record = await get_mutation(agent_id, mutation_id)
    if record is None:
        raise ContextRepoError("Mutation not found")
    if record.reverted_by:
        raise ContextRepoError("Mutation already reverted")
    if not record.reversible:
        raise ContextRepoError("Mutation is not reversible")

    parent_version = await get_repository_version(agent_id)
    now = _utc_now()
    revert_id = new_mutation_id()
    provenance = EntryProvenance(
        source_type="revert",
        source_id=mutation_id,
        mutation_id=revert_id,
        note=f"revert {record.action}",
        created_at=now,
    )

    if record.action == "create" and record.after is not None:
        updated = record.after.model_copy(update={"active": False, "superseded_by": revert_id})
        await update_fact(agent_id, updated, repo_version=parent_version + 1)
    elif record.action in {"update", "pin", "unpin", "delete", "consolidate"} and record.before is not None:
        restored = record.before.model_copy(
            update={
                "provenance": provenance,
                "active": True,
                "superseded_by": None,
            }
        )
        existing = await get_entry(agent_id, restored.id)
        if existing is None:
            await save_fact(
                agent_id=agent_id,
                entry=restored,
                repo_version=parent_version + 1,
                provenance=provenance,
                conflicts=restored.conflicts_with,
            )
        else:
            await update_fact(agent_id, restored, repo_version=parent_version + 1)
    else:
        raise ContextRepoError("Cannot revert this mutation type")

    next_version = parent_version + 1
    mutation = MutationRecord(
        mutation_id=revert_id,
        agent_id=agent_id,
        version_before=parent_version,
        version_after=next_version,
        action="revert",
        entry_id=record.entry_id,
        source=provenance,
        before=record.after,
        after=record.before,
        created_at=now,
    )
    repo = ContextRepoVersion(
        agent_id=agent_id,
        version=next_version,
        created_at=now,
        parent_version=parent_version,
        entries=await load_active_facts(agent_id),
    )
    await _snapshot_version(agent_id, repo, mutation)
    await mark_mutation_reverted(agent_id, mutation_id, reverted_by=revert_id)
    return repo


async def get_entry_permissions(agent_id: str, entry_id: str) -> list[dict[str, Any]]:
    return await list_permissions(agent_id, entry_id)


def context_repo_data_path() -> str:
    return str(data_dir() / "context-repos")
