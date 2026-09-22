from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class CommentaryActivitySnapshot:
    user_speaking: bool = False
    jarvis_speaking: bool = False
    jarvis_listening_to_user: bool = False
    urgent_alert_active: bool = False
    high_priority_tool_active: bool = False


class CommentaryRuntime:
    """Process-local activity flags consumed by the RFC-0055 interruption gates."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._activity = CommentaryActivitySnapshot()

    def snapshot(self) -> CommentaryActivitySnapshot:
        with self._lock:
            return CommentaryActivitySnapshot(
                user_speaking=self._activity.user_speaking,
                jarvis_speaking=self._activity.jarvis_speaking,
                jarvis_listening_to_user=self._activity.jarvis_listening_to_user,
                urgent_alert_active=self._activity.urgent_alert_active,
                high_priority_tool_active=self._activity.high_priority_tool_active,
            )

    def update(self, **kwargs: bool) -> CommentaryActivitySnapshot:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._activity, key):
                    setattr(self._activity, key, bool(value))
            return self.snapshot()


RUNTIME = CommentaryRuntime()
