import asyncio
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import settings

db_path = Path(settings.config_root) / "galleryloom.db"
db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    """Create tables and ensure WAL mode for SQLite."""
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await _apply_migrations(conn)

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

def init_db_sync():
    """Helper for scripts to init DB without manual asyncio boilerplate."""
    asyncio.run(init_db())


async def _apply_migrations(conn):
    """Lightweight, idempotent migrations for SQLite."""
    async def _has_column(table: str, column: str) -> bool:
        result = await conn.execute(text(f"PRAGMA table_info({table});"))
        cols = [row[1] for row in result.fetchall()]
        return column in cols

    # settings table additions
    settings_columns = [
        ("consider_images_in_subfolders", "BOOLEAN DEFAULT 0"),
        ("output_mode", "TEXT DEFAULT 'zip'"),
        ("copy_sidecars", "BOOLEAN DEFAULT 0"),
        ("lanraragi_flatten", "BOOLEAN DEFAULT 0"),
        ("archive_extension_for_galleries", "TEXT DEFAULT 'zip'"),
        ("debug_logging", "BOOLEAN DEFAULT 0"),
        ("auto_scan_enabled", "BOOLEAN DEFAULT 1"),
        ("auto_scan_interval_minutes", "INTEGER DEFAULT 30"),
    ]
    for col, ddl in settings_columns:
        if not await _has_column("settings", col):
            await conn.execute(text(f"ALTER TABLE settings ADD COLUMN {col} {ddl};"))

    # archive_records additions
    if not await _has_column("archive_records", "virtual_target_path"):
        await conn.execute(text("ALTER TABLE archive_records ADD COLUMN virtual_target_path TEXT;"))
