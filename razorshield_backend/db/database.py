"""
razorshield_backend/db/database.py
───────────────────────────────────
Async SQLAlchemy engine, session factory, and DB initialisation.

Key behaviours:
  - Normalises any Postgres URL flavour into an asyncpg-compatible one, dropping
    query parameters asyncpg cannot accept (channel_binding, sslmode, ...).
  - Enables the pgvector extension before running DDL migrations.
  - Provides a clean async context-manager session with auto-commit/rollback.
"""

import logging
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase

from razorshield_backend.config import get_settings

logger = logging.getLogger(__name__)


# ─── URL normalisation ────────────────────────────────────────────────────────

# Query params that asyncpg's connect() rejects outright. SSL is handled
# separately via connect_args, so sslmode is stripped rather than translated.
_UNSUPPORTED_QUERY_PARAMS = {
    "channel_binding",
    "sslmode",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "gssencmode",
    "target_session_attrs",
    "options",
}

# Scheme aliases that all mean "PostgreSQL". `postgres://` is what Heroku/Neon
# dashboards often hand out; the old string-replace only matched `postgresql://`
# and silently left such a URL with a driver SQLAlchemy could not resolve.
_PG_SCHEME_ALIASES = {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}


def _build_async_db_url(raw_url: str) -> str:
    """
    Convert a standard psql URL into an asyncpg-compatible one.

    - postgres:// | postgresql:// | postgresql+psycopg2://  →  postgresql+asyncpg://
    - Removes query params asyncpg cannot accept (channel_binding, sslmode, ...)
    - Leaves an already-asyncpg URL untouched apart from param cleaning.
    """
    if not raw_url or not raw_url.strip():
        raise ValueError("DATABASE_URL is empty — set it in your .env file.")

    parts = urlsplit(raw_url.strip())
    scheme = parts.scheme.lower()

    if scheme in _PG_SCHEME_ALIASES:
        scheme = "postgresql+asyncpg"
    elif scheme != "postgresql+asyncpg":
        raise ValueError(
            f"Unsupported DATABASE_URL scheme {parts.scheme!r}. "
            "Expected a postgresql:// (or postgresql+asyncpg://) connection string."
        )

    # Parse-and-rebuild rather than regex-substitute: this cannot leave behind a
    # dangling '?' or '&', regardless of parameter order.
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _UNSUPPORTED_QUERY_PARAMS
    ]

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def redact_db_url(url: str) -> str:
    """Mask the password so a connection string can be safely logged."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


# ─── Engine & session factory ─────────────────────────────────────────────────

settings = get_settings()
_async_db_url = _build_async_db_url(settings.database_url)

_is_testing = os.getenv("RAZORSHIELD_TESTING") == "1"

if _is_testing:
    # NullPool: no connection reuse — safe for pytest per-function event loops.
    engine = create_async_engine(
        _async_db_url,
        poolclass=NullPool,
        echo=False,
        connect_args={"ssl": "require"},
    )
else:
    engine = create_async_engine(
        _async_db_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=300,
        # Fail fast instead of hanging a request forever when the pool is drained.
        pool_timeout=30,
        echo=False,
        connect_args={"ssl": "require"},
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


async def check_connection() -> float:
    """
    Run a trivial round trip and return its latency in milliseconds.
    Raises on failure — used by the readiness probe.
    """
    import time

    start = time.monotonic()
    async with async_session_maker() as session:
        await session.execute(text("SELECT 1"))
    return (time.monotonic() - start) * 1000


async def dispose_engine() -> None:
    """Close all pooled connections. Called on application shutdown."""
    await engine.dispose()
    logger.info("Database engine disposed.")


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
