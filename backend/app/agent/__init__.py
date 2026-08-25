from __future__ import annotations

__all__ = ["AGENT"]


def __getattr__(name: str):
    if name == "AGENT":
        from .loop import AGENT

        return AGENT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
