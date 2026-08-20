from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import data_dir
from .models import Base

DB_PATH = data_dir() / "jarvis.db"
ENGINE = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH.as_posix()}", echo=False, future=True)
SessionLocal = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
