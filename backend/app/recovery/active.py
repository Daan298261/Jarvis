from __future__ import annotations

import threading

_lock = threading.RLock()
_active_rollback_id: str | None = None
_active_resource_classes: set[str] = set()


def set_active_rollback(run_id: str | None, resource_classes: set[str] | None = None) -> None:
    global _active_rollback_id, _active_resource_classes
    with _lock:
        _active_rollback_id = run_id
        _active_resource_classes = set(resource_classes or set())


def active_rollback_id() -> str | None:
    with _lock:
        return _active_rollback_id


def active_rollback_resource_classes() -> set[str]:
    with _lock:
        return set(_active_resource_classes)
