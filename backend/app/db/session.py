from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import data_dir
from .models import Base

DB_PATH = data_dir() / "jarvis.db"
ENGINE: AsyncEngine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH.as_posix()}",
    echo=False,
    future=True,
    connect_args={"timeout": 30},
)
_sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


class _SessionLocal:
    """Look up the current sessionmaker so tests can swap the database."""

    def __call__(self, *args, **kwargs) -> AsyncSession:
        return _sessionmaker(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_sessionmaker, name)


SessionLocal = _SessionLocal()


async def dispose_database_engine() -> None:
    """Close pooled aiosqlite workers so they cannot post to a closed event loop."""
    await ENGINE.dispose()


async def configure_database(url: str | None = None, path: Path | None = None) -> None:
    """Point the process at a new DB URL, disposing the previous engine first.

    Reassigning ``ENGINE`` without dispose orphans aiosqlite worker threads
    (PR #531 class). Callers must await this so the old pool is closed before
    the event loop ends.
    """
    global ENGINE, _sessionmaker, DB_PATH
    old = ENGINE
    if path is not None:
        DB_PATH = Path(path)
        url = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
    if not url:
        url = f"sqlite+aiosqlite:///{data_dir().joinpath('jarvis.db').as_posix()}"
    ENGINE = create_async_engine(url, echo=False, future=True, connect_args={"timeout": 30})
    _sessionmaker = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)
    if old is not None and old is not ENGINE:
        await old.dispose()


def _add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("tasks")}
    statements = []
    for table in ("trajectories", "coding_usage"):
        if table in inspector.get_table_names() and "completion_id" not in {c["name"] for c in inspector.get_columns(table)}:
            statements.append(f"ALTER TABLE {table} ADD COLUMN completion_id VARCHAR(36) DEFAULT ''")
    if "execution_mode" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN execution_mode VARCHAR(32) DEFAULT 'balanced'")
    if "task_class" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN task_class VARCHAR(64) DEFAULT ''")
    if "security_role" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN security_role VARCHAR(32) DEFAULT ''")
    if "response_route" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN response_route VARCHAR(32) DEFAULT 'managed_task'")
    if "first_response_ms" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN first_response_ms FLOAT DEFAULT 0")
    if "model_calls" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN model_calls INTEGER DEFAULT 0")
    if "tool_call_count" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN tool_call_count INTEGER DEFAULT 0")
    if "schema_errors" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN schema_errors INTEGER DEFAULT 0")
    if "model_ms" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN model_ms FLOAT DEFAULT 0")
    if "tool_ms" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN tool_ms FLOAT DEFAULT 0")
    if "human_interventions" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN human_interventions INTEGER DEFAULT 0")
    if "exposed_tools" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN exposed_tools TEXT DEFAULT ''")
    if "specialist_persona_ids" not in columns:
        statements.append("ALTER TABLE tasks ADD COLUMN specialist_persona_ids TEXT DEFAULT '[]'")
    if "task_events" in inspector.get_table_names():
        event_cols = {col["name"] for col in inspector.get_columns("task_events")}
        if "source" not in event_cols:
            statements.append("ALTER TABLE task_events ADD COLUMN source VARCHAR(120) DEFAULT 'jarvis-agent'")
    if "benchmark_samples" in inspector.get_table_names():
        bench_cols = {col["name"] for col in inspector.get_columns("benchmark_samples")}
        if "metrics_json" not in bench_cols:
            statements.append("ALTER TABLE benchmark_samples ADD COLUMN metrics_json TEXT DEFAULT '{}'")
    if "conversations" in inspector.get_table_names():
        conv_cols = {col["name"] for col in inspector.get_columns("conversations")}
        if "project_id" not in conv_cols:
            statements.append("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(36) DEFAULT ''")
    if statements:
        try:
            from ..recovery.hooks import RISK_SCHEMA_MIGRATION, ensure_checkpoint_before_risk

            ensure_checkpoint_before_risk(RISK_SCHEMA_MIGRATION, notes=f"columns:{len(statements)}")
        except Exception:
            pass
    for statement in statements:
        sync_conn.execute(text(statement))


def _prepare_outbox_upgrade(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "post_response_jobs" not in inspector.get_table_names():
        return
    if "completion_id" in {c["name"] for c in inspector.get_columns("post_response_jobs")}:
        return
    # Keep every legacy row in a backup table, including pending and failed jobs.
    # The new primary key adds a completion ID so follow-ups can coexist.
    if "post_response_jobs_0247_backup" in inspector.get_table_names():
        raise RuntimeError("Outbox migration backup already exists; refusing to overwrite it")
    sync_conn.execute(text("ALTER TABLE post_response_jobs RENAME TO post_response_jobs_0247_backup"))
    sync_conn.execute(text("DROP INDEX IF EXISTS ix_post_response_jobs_status"))


def _copy_legacy_outbox(sync_conn) -> None:
    if "post_response_jobs_0247_backup" not in inspect(sync_conn).get_table_names():
        return
    sync_conn.execute(text("""
        INSERT OR IGNORE INTO post_response_jobs
            (task_id, completion_id, kind, released, payload, status, attempts, available_at, last_error)
        SELECT old.task_id, '', old.kind,
            EXISTS(SELECT 1 FROM task_events e WHERE e.task_id=old.task_id AND e.kind='completed'),
            old.payload, old.status, old.attempts, old.available_at, old.last_error
        FROM post_response_jobs_0247_backup old
    """))


async def init_db() -> None:
    async with ENGINE.begin() as conn:
        await conn.run_sync(_prepare_outbox_upgrade)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_copy_legacy_outbox)
        # create_all does not add indexes to pre-existing tables during upgrades.
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_events_task_kind ON task_events (task_id, kind)"))
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=30000"))


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
