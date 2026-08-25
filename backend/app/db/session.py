from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import data_dir
from .models import Base

DB_PATH = data_dir() / "jarvis.db"
ENGINE = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH.as_posix()}",
    echo=False,
    future=True,
    connect_args={"timeout": 30},
)
SessionLocal = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


async def _ensure_task_columns(conn) -> None:
    result = await conn.exec_driver_sql("PRAGMA table_info(tasks)")
    names = {row[1] for row in result.fetchall()}
    if "execution_mode" not in names:
        await conn.exec_driver_sql(
            "ALTER TABLE tasks ADD COLUMN execution_mode VARCHAR(32) NOT NULL DEFAULT 'balanced'"
        )
    if "task_class" not in names:
        await conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN task_class VARCHAR(64) NOT NULL DEFAULT ''")
    if "selected_worker" not in names:
        await conn.exec_driver_sql(
            "ALTER TABLE tasks ADD COLUMN selected_worker VARCHAR(64) NOT NULL DEFAULT ''"
        )


async def init_db() -> None:
    async with ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_task_columns(conn)
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.exec_driver_sql("PRAGMA busy_timeout=5000")


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
