"""Optional worker adapters. Jarvis stays the orchestrator; these never replace native tools."""

from .browser import BrowserUseBackend, playwright_is_default
from .code import OpenHandsBackend
from .voice import voice_status

__all__ = [
    "BrowserUseBackend",
    "OpenHandsBackend",
    "playwright_is_default",
    "voice_status",
]
