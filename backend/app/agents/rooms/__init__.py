"""Agent Rooms public API (RFC-0174).

Owner-visible multi-agent collaboration with Anzu as supervisor, typed
messages, bounded Blackboard, deadlock control, and resource governor.
"""

from __future__ import annotations

from .audit import AUDIT_KINDS, AuditEvent, RoomAuditLog
from .blackboard import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_ENTRY_CHARS,
    DEFAULT_MAX_TOTAL_CHARS,
    Blackboard,
    BlackboardBoundError,
    BlackboardEntry,
    BlackboardKind,
)
from .deadlock import (
    DeadlockConfig,
    DeadlockIssue,
    DeadlockIssueKind,
    DeadlockMonitor,
    DeadlockResolution,
    ResolutionAction,
)
from .governor import (
    COST_MODES,
    PRIVACY_MODES,
    GovernorDenied,
    ResourceBudget,
    ResourceClaim,
    ResourceGovernor,
    ResourceLease,
    build_budget,
)
from .history import PrivateHistoryStore, PrivateTurn
from .protocol import (
    MESSAGE_KINDS,
    MessageKind,
    RoomMessage,
    build_message,
    message_fingerprint,
    parse_mentions,
    parse_message_kind,
    sanitize_public_text,
    strip_hidden_fields,
)
from .room import (
    AgentRoom,
    Participant,
    RoomError,
    RoomTerminated,
    create_room,
    get_room,
    list_rooms,
    mention_targets,
    reset_registry,
)
from .router_hooks import (
    RoomRoutingHint,
    extract_specialist_mentions,
    open_room_from_hint,
    suggest_room_routing,
)
from .supervisor import SUPERVISOR_ID, Supervisor, SynthesisResult, TaskGraph, TaskNode

__all__ = [
    "AUDIT_KINDS",
    "AuditEvent",
    "AgentRoom",
    "Blackboard",
    "BlackboardBoundError",
    "BlackboardEntry",
    "BlackboardKind",
    "COST_MODES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_ENTRY_CHARS",
    "DEFAULT_MAX_TOTAL_CHARS",
    "DeadlockConfig",
    "DeadlockIssue",
    "DeadlockIssueKind",
    "DeadlockMonitor",
    "DeadlockResolution",
    "GovernorDenied",
    "MESSAGE_KINDS",
    "MessageKind",
    "PRIVACY_MODES",
    "Participant",
    "PrivateHistoryStore",
    "PrivateTurn",
    "ResolutionAction",
    "ResourceBudget",
    "ResourceClaim",
    "ResourceGovernor",
    "ResourceLease",
    "RoomAuditLog",
    "RoomError",
    "RoomMessage",
    "RoomRoutingHint",
    "RoomTerminated",
    "SUPERVISOR_ID",
    "Supervisor",
    "SynthesisResult",
    "TaskGraph",
    "TaskNode",
    "build_budget",
    "build_message",
    "create_room",
    "extract_specialist_mentions",
    "get_room",
    "list_rooms",
    "mention_targets",
    "message_fingerprint",
    "open_room_from_hint",
    "parse_mentions",
    "parse_message_kind",
    "reset_registry",
    "sanitize_public_text",
    "strip_hidden_fields",
    "suggest_room_routing",
]
