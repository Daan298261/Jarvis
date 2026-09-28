"""Whether the Jarvis backend process is running elevated."""

from __future__ import annotations

import os
import sys


def is_elevated() -> bool:
    if os.name != "nt":
        try:
            return os.geteuid() == 0  # type: ignore[attr-defined]
        except AttributeError:
            return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def snapshot() -> dict[str, object]:
    return {
        "elevated": is_elevated(),
        "pid": os.getpid(),
        "executable": sys.executable,
        "platform": os.name,
    }
