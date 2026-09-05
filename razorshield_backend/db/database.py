"""
razorshield_backend/db/database.py
───────────────────────────────────
Async SQLAlchemy engine, session factory, and DB initialisation.

Key behaviours:
  - Strips `channel_binding=require` from the Neon connection string (asyncpg
    does not support this parameter and will raise a ConnectionError).
  - Enables the pgvector extension before running DDL migrations.
  - Provides a clean async context-manager session with auto-commit/rollback.
"""

import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from razorshield_backend.config import get_settings

logger = logging.getLogger(__name__)


# ─── URL normalisation ────────────────────────────────────────────────────────

def _build_async_db_url(raw_url: str) -> str:
    """
    Convert a standard psql URL into an asyncpg-compatible one.

    Changes:
      postgresql://  →  postgresql+asyncpg://
      Removes ?channel_binding=...  (asyncpg doesn't support it)
      Converts ?sslmode=require → handled via connect_args instead
    """
    url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Strip channel_binding parameter (may appear as ?x=y&channel_binding=z
    # or as the sole query param)
    url = re.sub(r"[&?]channel_binding=[^&\s]*", "", url)

    # Remove dangling ? or trailing &
    url = re.sub(r"\?&", "?", url)
    url = url.rstrip("?&")

    # Remove sslmode from query string — we pass ssl via connect_args
    url = re.sub(r"[&?]sslmode=[^&\s]*", "", url)
    url = re.sub(r"\?&", "?", url)
    url = url.rstrip("?&")

    return url


# ─── Engine & session factory ─────────────────────────────────────────────────

settings = get_settings()
_async_db_url = _build_async_db_url(settings.database_url)

engine = create_async_engine(
    _async_db_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,           # verify connections before use
    pool_recycle=300,             # recycle connections every 5 min
    echo=False,
    connect_args={"ssl": "require"},   # Neon requires TLS
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # prevent lazy-load errors after commit
)


# ─── ORM base ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base for all ORM models."""
    pass


# ─── Startup initialisation ───────────────────────────────────────────────────

async def init_db() -> None:
    """
    Enable pgvector extension and auto-create all ORM tables.
    Called once during FastAPI startup lifespan.
    """
    async with engine.begin() as conn:
        # pgvector must exist before any Vector column DDL
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("pgvector extension enabled.")

        # Import models here to ensure they are registered against Base
        import razorshield_backend.db.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialised.")


# ─── Session dependency ────────────────────────────────────────────────────────

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that yields an SQLAlchemy session.
    Automatically commits on success and rolls back on any exception.

    Usage:
        async with get_session() as session:
            result = await session.execute(...)
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
