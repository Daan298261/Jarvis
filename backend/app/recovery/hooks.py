from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Iterator

from .checkpoint import create_checkpoint
from .journal import journal_mutate, reconcile_pending_entries
from .resources import capture_policy_platform, capture_policy_profiles, capture_settings_control, capture_workflows
from .types import (
    RESOURCE_POLICY_PLATFORM,
    RESOURCE_POLICY_PROFILES,
    RESOURCE_SETTINGS_CONTROL,
    RESOURCE_WORKFLOWS,
    JournalOperation,
)

_skip_journal: contextvars.ContextVar[bool] = contextvars.ContextVar("recovery_skip_journal", default=False)

RISK_SCHEMA_MIGRATION = "schema_migration"
RISK_SELF_IMPROVEMENT = "self_improvement"
RISK_BULK_POLICY = "bulk_policy"
RISK_PACK_RUNTIME = "pack_runtime_upgrade"


@contextlib.contextmanager
def skip_journal() -> Iterator[None]:
    token = _skip_journal.set(True)
    try:
        yield
    finally:
        _skip_journal.reset(token)


def journaling_enabled() -> bool:
    return not _skip_journal.get()


def startup_recovery() -> dict[str, Any]:
    aborted = reconcile_pending_entries()
    return {"aborted_pending_journal_seqs": aborted}


def ensure_checkpoint_before_risk(
    risk_tag: str,
    *,
    actor: str = "system",
    notes: str = "",
) -> dict[str, Any]:
    """Create a CANDIDATE checkpoint before high-risk mutations."""
    return create_checkpoint(notes=f"{risk_tag}: {notes}".strip(), actor=actor)


def record_policy_profiles_mutation(
    *,
    profile_id: str,
    operation: JournalOperation,
    actor: str,
    before: dict[str, Any] | None,
    apply_fn,
    correlation_id: str | None = None,
    replay_safe: bool = False,
) -> int | None:
    if not journaling_enabled():
        apply_fn()
        return None
    return journal_mutate(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id=profile_id,
        operation=operation,
        actor=actor,
        before=before,
        after_fn=capture_policy_profiles,
        correlation_id=correlation_id,
        replay_safe=replay_safe,
        apply_fn=apply_fn,
    )


def record_policy_platform_mutation(
    *,
    actor: str,
    before: dict[str, Any],
    apply_fn,
    risk_tag: str | None = RISK_BULK_POLICY,
) -> int | None:
    if not journaling_enabled():
        apply_fn()
        return None
    return journal_mutate(
        resource_class=RESOURCE_POLICY_PLATFORM,
        resource_id="platform",
        operation=JournalOperation.UPDATE,
        actor=actor,
        before=before,
        after_fn=capture_policy_platform,
        risk_tag=risk_tag,
        replay_safe=True,
        apply_fn=apply_fn,
    )


def record_workflow_mutation(
    *,
    workflow_id: str,
    operation: JournalOperation,
    actor: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    apply_fn,
) -> int | None:
    if not journaling_enabled():
        apply_fn()
        return None
    return journal_mutate(
        resource_class=RESOURCE_WORKFLOWS,
        resource_id=workflow_id,
        operation=operation,
        actor=actor,
        before={"workflows": before} if before is not None else None,
        after_fn=capture_workflows,
        replay_safe=False,
        apply_fn=apply_fn,
    )


def record_settings_control_mutation(
    *,
    actor: str,
    before: dict[str, Any],
    apply_fn,
    risk_tag: str | None = None,
) -> int | None:
    if not journaling_enabled():
        apply_fn()
        return None
    return journal_mutate(
        resource_class=RESOURCE_SETTINGS_CONTROL,
        resource_id="control_plane",
        operation=JournalOperation.UPDATE,
        actor=actor,
        before=before,
        after_fn=capture_settings_control,
        risk_tag=risk_tag,
        replay_safe=True,
        apply_fn=apply_fn,
    )


def wrap_settings_save(apply_fn, *, actor: str = "settings") -> None:
    before = capture_settings_control()
    if not journaling_enabled():
        apply_fn()
        return
    record_settings_control_mutation(actor=actor, before=before, apply_fn=apply_fn)


def snapshot_blocks_for_tests() -> dict[str, Any]:
    return {
        RESOURCE_POLICY_PROFILES: capture_policy_profiles(),
        RESOURCE_POLICY_PLATFORM: capture_policy_platform(),
        RESOURCE_WORKFLOWS: capture_workflows(),
        RESOURCE_SETTINGS_CONTROL: capture_settings_control(),
    }
