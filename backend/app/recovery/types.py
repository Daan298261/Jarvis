from __future__ import annotations

from enum import StrEnum


class CheckpointTag(StrEnum):
    CANDIDATE = "CANDIDATE"
    KNOWN_GOOD = "KNOWN_GOOD"
    INVALID = "INVALID"


class RollbackPhase(StrEnum):
    PLAN = "PLAN"
    QUIESCE = "QUIESCE"
    CHECKPOINT_CURRENT = "CHECKPOINT_CURRENT"
    RESTORE = "RESTORE"
    REPLAY_IF_REQUESTED = "REPLAY_IF_REQUESTED"
    VERIFY = "VERIFY"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class JournalOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"


class CommitState(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    ABORTED = "aborted"


# Registered control-plane resource classes (bounded initial set).
RESOURCE_POLICY_PROFILES = "policy.profiles"
RESOURCE_POLICY_PLATFORM = "policy.platform"
RESOURCE_WORKFLOWS = "workflows.custom"
RESOURCE_SETTINGS_CONTROL = "settings.control_plane"
RESOURCE_PACKS_STATE = "packs.installations"

ALL_RESOURCE_CLASSES = frozenset(
    {
        RESOURCE_POLICY_PROFILES,
        RESOURCE_POLICY_PLATFORM,
        RESOURCE_WORKFLOWS,
        RESOURCE_SETTINGS_CONTROL,
        RESOURCE_PACKS_STATE,
    }
)

JOURNAL_SCHEMA_VERSION = 1
