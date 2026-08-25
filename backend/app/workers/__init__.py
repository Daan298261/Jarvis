"""Optional worker adapters. Jarvis stays the orchestrator; these never replace native tools."""

from .browser import BrowserUseBackend, playwright_is_default
from .code import OpenHandsBackend
from .computer import CuaBackend, NativeWindowsBackend, UFOBackend
from .interpreter import OpenInterpreterBackend
from .voice import voice_status

__all__ = [
    "BrowserUseBackend",
    "CuaBackend",
    "NativeWindowsBackend",
    "OpenHandsBackend",
    "OpenInterpreterBackend",
    "UFOBackend",
    "playwright_is_default",
    "voice_status",
]
