"""PyInstaller entrypoint for the Jarvis FastAPI backend sidecar.

Runs uvicorn serving app.main:app on 127.0.0.1:4780 by default.
Optional deps that fail to import are reported at runtime rather than crashing startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_root() -> Path:
    if getattr(sys, "frozen", False):
        # one-folder: jarvis-backend.exe lives in sidecars/jarvis-backend/
        return Path(sys.executable).resolve().parent.parent.parent
    env = os.environ.get("JARVIS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def main() -> None:
    root = _resolve_root()
    os.environ.setdefault("JARVIS_ROOT", str(root))
    backend = root / "backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    # When frozen, app package is bundled beside the exe.
    bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    if str(bundled) not in sys.path:
        sys.path.insert(0, str(bundled))

    host = os.environ.get("JARVIS_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("JARVIS_BIND_PORT", "4780"))

    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
