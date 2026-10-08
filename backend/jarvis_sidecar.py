"""PyInstaller entrypoint for the Jarvis FastAPI backend sidecar.

Runs uvicorn serving app.main:app on 127.0.0.1:4780 by default.
Optional deps that fail to import are reported at runtime rather than crashing startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_root() -> Path:
    env = os.environ.get("JARVIS_ROOT")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # Inno layout: {app}/desktop/sidecars/jarvis-backend/jarvis-backend.exe
        return Path(sys.executable).resolve().parents[3]
    return Path(__file__).resolve().parents[1]


def _verify_frozen_imports() -> None:
    """Fail the sidecar build when the default voice stack was not collected."""
    missing: list[str] = []
    for name in ("kokoro", "soundfile"):
        try:
            __import__(name)
        except Exception as exc:
            missing.append(f"{name}: {exc}")
    if missing:
        print("Frozen import check failed: " + "; ".join(missing), file=sys.stderr)
        raise SystemExit(1)
    print("Frozen import check ok: kokoro, soundfile")


def main() -> None:
    if "--verify-frozen-imports" in sys.argv:
        _verify_frozen_imports()
        return
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
