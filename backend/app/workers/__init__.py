"""Optional worker adapters. Jarvis stays the orchestrator; these never replace native tools."""

from .browser import BrowserUseBackend, playwright_is_default

__all__ = [
    "BrowserUseBackend",
    "playwright_is_default",
]
