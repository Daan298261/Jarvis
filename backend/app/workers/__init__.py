"""Optional worker adapters. Jarvis stays the orchestrator; these never replace native tools."""

from .computer import CuaBackend, NativeWindowsBackend, UFOBackend, preferred_computer_backend

__all__ = [
    "CuaBackend",
    "NativeWindowsBackend",
    "UFOBackend",
    "preferred_computer_backend",
]
