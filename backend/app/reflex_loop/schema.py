"""Atomic ActionFrame schema for browser and desktop (RFC-0172)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
import time
import uuid


class SurfaceKind(str, Enum):
    BROWSER = "browser"
    DESKTOP = "desktop"


class Operation(str, Enum):
    """Bounded operations the Reflex Lane may select. No selector/JS/shell."""

    CLICK = "CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    CLEAR = "CLEAR"
    FOCUS = "FOCUS"
    TOGGLE = "TOGGLE"
    SELECT = "SELECT"
    SCROLL_INTO_VIEW = "SCROLL_INTO_VIEW"
    PRESS_KEY = "PRESS_KEY"
    DONE = "DONE"
    BLOCK = "BLOCK"


# Operations that mutate UI state and require postcondition verification.
MUTATING_OPERATIONS = frozenset(
    {
        Operation.CLICK,
        Operation.TYPE_TEXT,
        Operation.CLEAR,
        Operation.TOGGLE,
        Operation.SELECT,
        Operation.PRESS_KEY,
    }
)

# Fast path may never accept these as model-invented payloads.
FORBIDDEN_FAST_PATH_KEYS = frozenset(
    {
        "selector",
        "css",
        "xpath",
        "js",
        "javascript",
        "script",
        "shell",
        "command",
        "coordinate",
        "coordinates",
        "x",
        "y",
        "pixel",
    }
)


@dataclass(frozen=True)
class Geometry:
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


@dataclass(frozen=True)
class NodeState:
    enabled: bool = True
    focused: bool = False
    checked: bool | None = None
    expanded: bool | None = None
    selected: bool | None = None
    readonly: bool = False
    busy: bool = False
    occluded: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionNode:
    """One actionable control observed in a frame."""

    target_id: str
    role: str
    name: str
    value: str = ""
    state: NodeState = field(default_factory=NodeState)
    geometry: Geometry = field(default_factory=Geometry)
    visible: bool = True
    supported_operations: tuple[Operation, ...] = field(default_factory=tuple)
    # Native/DOM identity for re-resolution — never model-authored.
    backend_ref: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = _node_fingerprint(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "state": self.state.as_dict(),
            "geometry": self.geometry.as_dict(),
            "visible": self.visible,
            "supported_operations": [op.value for op in self.supported_operations],
            "backend_ref": dict(self.backend_ref),
            "fingerprint": self.fingerprint,
        }

    def supports(self, operation: Operation) -> bool:
        return operation in self.supported_operations


@dataclass
class ActionFrame:
    """Atomic semantic snapshot shared by browser and desktop adapters."""

    frame_id: str
    surface: SurfaceKind
    app_or_page_id: str
    timestamp_ms: float
    nodes: list[ActionNode] = field(default_factory=list)
    focus_target_id: str | None = None
    url_or_title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "surface": self.surface.value,
            "app_or_page_id": self.app_or_page_id,
            "timestamp_ms": self.timestamp_ms,
            "nodes": [n.as_dict() for n in self.nodes],
            "focus_target_id": self.focus_target_id,
            "url_or_title": self.url_or_title,
            "meta": dict(self.meta),
        }

    def node_by_id(self, target_id: str) -> ActionNode | None:
        for node in self.nodes:
            if node.target_id == target_id:
                return node
        return None

    def age_ms(self, now_ms: float | None = None) -> float:
        now = time.time() * 1000.0 if now_ms is None else now_ms
        return max(0.0, now - self.timestamp_ms)

    def compact_state(self) -> dict[str, Any]:
        """Projection for Reflex Lane — no backend handles or coordinates as freeform."""
        return {
            "frame_id": self.frame_id,
            "surface": self.surface.value,
            "app_or_page_id": self.app_or_page_id,
            "url_or_title": self.url_or_title,
            "focus_target_id": self.focus_target_id,
            "nodes": [
                {
                    "target_id": n.target_id,
                    "role": n.role,
                    "name": n.name,
                    "value": n.value[:200],
                    "visible": n.visible,
                    "enabled": n.state.enabled,
                    "occluded": n.state.occluded,
                    "ops": [op.value for op in n.supported_operations],
                }
                for n in self.nodes
            ],
        }


@dataclass(frozen=True)
class ReflexDecision:
    """One typed decision: operation + optional target + terminal state."""

    operation: Operation
    target_id: str | None = None
    done: bool = False
    blocked: bool = False
    reason: str = ""
    confidence: float = 1.0
    text_hint: str = ""
    provider: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "target_id": self.target_id,
            "done": self.done,
            "blocked": self.blocked,
            "reason": self.reason,
            "confidence": self.confidence,
            "text_hint": self.text_hint,
            "provider": self.provider,
        }


def new_frame_id() -> str:
    return f"af_{uuid.uuid4().hex[:16]}"


def new_target_id(index: int) -> str:
    return f"t{index}"


def _node_fingerprint(node: ActionNode) -> str:
    ref = node.backend_ref
    parts = [
        node.role.strip().lower(),
        node.name.strip().lower(),
        str(ref.get("automation_id") or ref.get("dom_id") or ref.get("cdp_backend_node_id") or ""),
        str(ref.get("control_type") or ""),
    ]
    return "|".join(parts)
