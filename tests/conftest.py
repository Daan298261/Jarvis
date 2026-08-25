from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import AppSettings


@pytest.fixture
async def jarvis_env(tmp_path, monkeypatch):
    from app.db import session as session_mod

    db_path = tmp_path / "jarvis.db"
    session_mod.configure_database(path=db_path)
    await session_mod.init_db()

    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        autonomy="autonomous",
        execution_mode="balanced",
        backup_enabled=False,
    )
    monkeypatch.setattr("app.agent.loop.load_settings", lambda: settings)
    monkeypatch.setattr("app.config.load_settings", lambda: settings)
    monkeypatch.setattr("app.agent.queue_watcher.data_dir", lambda: tmp_path)

    from app.inference.manager import MANAGER
    from app.tools.registry import REGISTRY

    MANAGER.state.loaded = True
    MANAGER.state.last_error = ""
    MANAGER.state.context_size = 16384
    MANAGER.backend = None
    REGISTRY.apply_settings(settings)
    yield {"tmp": tmp_path, "settings": settings, "manager": MANAGER}
    MANAGER.provider = None
    MANAGER.state.loaded = False
    REGISTRY.bind_exposure(None)
