from __future__ import annotations

from typing import Any

__all__ = ["AGENT"]


def __getattr__(name: str) -> Any:
    if name == "AGENT":
        from .loop import AGENT

        return AGENT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
