from __future__ import annotations

import threading
from typing import Iterable

from .active import active_rollback_resource_classes

_lock = threading.RLock()
_blocked_classes: set[str] = set()
_blocked_ids: dict[str, set[str]] = {}


class WriteAdmissionError(PermissionError):
    """Raised when a mutation is rejected during rollback quiesce."""


def begin_rollback_admission(resource_classes: Iterable[str]) -> None:
    with _lock:
        for item in resource_classes:
            _blocked_classes.add(item)


def end_rollback_admission() -> None:
    with _lock:
        _blocked_classes.clear()
        _blocked_ids.clear()


def assert_write_allowed(resource_class: str, resource_id: str = "*") -> None:
    active = active_rollback_resource_classes()
    blocked = set(_blocked_classes) | active
    if resource_class in blocked:
        raise WriteAdmissionError(
            f"Writes to {resource_class} are blocked while recovery rollback is in progress"
        )
    ids = _blocked_ids.get(resource_class)
    if ids and resource_id in ids:
        raise WriteAdmissionError(
            f"Writes to {resource_class}:{resource_id} are blocked during recovery rollback"
        )


def admission_status() -> dict[str, object]:
    return {
        "blocked_resource_classes": sorted(set(_blocked_classes) | active_rollback_resource_classes()),
    }
