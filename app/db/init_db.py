"""Database initialisation helper.

For SQLite (local dev): creates all tables directly via SQLAlchemy create_all.
For PostgreSQL: tables are managed by Alembic migrations.
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)


async def create_tables() -> None:
    """Create all tables if they don't exist (SQLite / dev mode)."""
    from app.db.base import Base
    from app.db.session import engine
    import app.models  # noqa: F401 — registers all ORM models with Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("db_tables_created_or_verified")
