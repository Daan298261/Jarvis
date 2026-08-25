from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import data_dir
from .models import Base

DB_PATH = data_dir() / "jarvis.db"
ENGINE: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH.as_posix()}", echo=False, future=True)
_sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


class _SessionLocal:
    """Look up the current sessionmaker so tests can swap the database."""

    def __call__(self, *args, **kwargs) -> AsyncSession:
        return _sessionmaker(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_sessionmaker, name)


SessionLocal = _SessionLocal()


def configure_database(url: str | None = None, path: Path | None = None) -> None:
    global ENGINE, _sessionmaker, DB_PATH
    if path is not None:
        DB_PATH = Path(path)
        url = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
    if not url:
        url = f"sqlite+aiosqlite:///{data_dir().joinpath('jarvis.db').as_posix()}"
    ENGINE = create_async_engine(url, echo=False, future=True)
    _sessionmaker = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("tasks")}
    statements = []
    if "execution_mode" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN execution_mode VARCHAR(32) DEFAULT 'balanced'")
    if "task_class" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN task_class VARCHAR(64) DEFAULT ''")
    tables = inspector.get_table_names()
    if "benchmark_samples" in tables:
        bench_cols = {col["name"] for col in inspector.get_columns("benchmark_samples")}
        if "notes" not in bench_cols:
            statements.append("ALTER TABLE benchmark_samples ADD COLUMN notes TEXT DEFAULT ''")
    for statement in statements:
        sync_conn.execute(text(statement))


async def init_db() -> None:
    async with ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
