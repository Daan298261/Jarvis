from __future__ import annotations

from contextlib import contextmanager
from threading import local

from .types import CrashBoundary

_tls = local()


class SimulatedWorkerDeath(Exception):
    """Raised when crash-injection terminates the worker at a persistence boundary."""

    def __init__(self, boundary: CrashBoundary, step_key: str = "") -> None:
        self.boundary = boundary
        self.step_key = step_key
        super().__init__(f"simulated worker death at {boundary.value}")


def configure_crash_injection(boundaries: set[tuple[str, CrashBoundary]] | None) -> None:
    _tls.crash_matrix = boundaries


def clear_crash_injection() -> None:
    _tls.crash_matrix = None


def _matrix() -> set[tuple[str, CrashBoundary]] | None:
    return getattr(_tls, "crash_matrix", None)


def check_crash_boundary(step_key: str, boundary: CrashBoundary) -> None:
    matrix = _matrix()
    if not matrix:
        return
    if (step_key, boundary) in matrix or ("*", boundary) in matrix:
        raise SimulatedWorkerDeath(boundary, step_key)


@contextmanager
def crash_at(step_key: str, boundary: CrashBoundary):
    configure_crash_injection({(step_key, boundary)})
    try:
        yield
    finally:
        clear_crash_injection()
