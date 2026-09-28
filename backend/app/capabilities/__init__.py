"""Capability parity registry and lab (RFC-0137)."""

from .registry import capability_summary, get_capability, list_capabilities, load_registry

__all__ = [
    "capability_summary",
    "get_capability",
    "list_capabilities",
    "load_registry",
]
