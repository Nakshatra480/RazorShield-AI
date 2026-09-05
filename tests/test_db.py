"""
tests/test_db.py
─────────────────────────────────────────────────────────────────────────────
Database & pgvector layer tests.

Key design decisions:
  - Each test opens its own session (NullPool in test mode avoids loop conflicts).
  - Vector values are written as SQL literals rather than bind parameters,
    matching what the production catalog agent does: asyncpg cannot cast a bound
    Python string to the pgvector type.
  - Everything a later statement needs to see is COMMITTED first. Temp tables and
    uncommitted rows are connection-local, so a second connection cannot observe
    them — that was the cause of both pre-existing failures in this module.
"""

import math
import uuid

import pytest
from sqlalchemy import delete, select, text

from razorshield_backend.agents.catalog_agent import to_vector_literal

pytestmark = pytest.mark.usefixtures("require_db")

VECTOR_DIM = 768


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_connection(initialised_db):
    """
    Assert active connection to Neon PostgreSQL via asyncpg.
    SELECT 1 — any auth or network failure raises here.
    """
    async with initialised_db() as session:
        result = await session.execute(text("SELECT 1 AS alive"))
        row = result.fetchone()

    assert row is not None, "DB returned no rows for SELECT 1"
    assert row[0] == 1, f"Expected 1, got {row[0]}"
    print("\n  [PASS] Neon PostgreSQL connection alive.")


@pytest.mark.asyncio
async def test_vector_extension(initialised_db):
    """
    Verify pgvector is enabled and computes 768-dim cosine distance correctly.

    Two orthogonal unit vectors must have cosine distance exactly 1.0.
    (A zero vector has undefined cosine distance — magnitude 0 → NaN — so unit
    vectors are used instead.)

    Previously this test created a TEMP table on a SQLAlchemy connection and then
    inserted into it from a *separate* raw asyncpg connection. Temp tables live
    in a per-connection schema, so the second connection could not see the table
    at all. Everything now runs on one session.
    """
    table = f"_tv_{uuid.uuid4().hex[:8]}"

    e1 = [1.0] + [0.0] * (VECTOR_DIM - 1)          # unit vector along dim 0
    e2 = [0.0, 1.0] + [0.0] * (VECTOR_DIM - 2)     # unit vector along dim 1
    vec1, vec2 = to_vector_literal(e1), to_vector_literal(e2)

    async with initialised_db() as session:
        await session.execute(
            text(f"CREATE TEMP TABLE {table} (id int PRIMARY KEY, vec vector({VECTOR_DIM}))")
        )
        await session.execute(
            text(
                f"INSERT INTO {table} (id, vec) VALUES "
                f"(1, '{vec1}'::vector), (2, '{vec2}'::vector)"
            )
        )
        row = (
            await session.execute(
                text(
                    f"SELECT (a.vec <=> b.vec)::float8 AS dist "
                    f"FROM {table} a, {table} b WHERE a.id = 1 AND b.id = 2"
                )
            )
        ).fetchone()
        await session.execute(text(f"DROP TABLE IF EXISTS {table}"))

    assert row is not None, "Cosine distance query returned no rows"
    dist = float(row[0])
    assert not math.isnan(dist), "Cosine distance is NaN — check vector magnitudes"
    assert 0.0 <= dist <= 2.0, f"Cosine distance out of [0,2]: {dist}"
    assert abs(dist - 1.0) < 0.01, f"Expected dist≈1.0 for orthogonal vectors, got {dist}"
    print(f"\n  [PASS] pgvector {VECTOR_DIM}-dim cosine distance = {dist:.6f}")


@pytest.mark.asyncio
async def test_merchant_crud(initialised_db):
    """Full CRUD lifecycle on the merchants table: CREATE → READ → UPDATE → DELETE."""
    from razorshield_backend.db.models import Merchant

    test_url = f"https://test-{uuid.uuid4().hex[:8]}.example.com"

    async with initialised_db() as session:
        # CREATE
        merchant = Merchant(domain_url=test_url)
        session.add(merchant)
        await session.flush()
        mid = merchant.id
        assert mid is not None, "Merchant.id not assigned after flush"
        print(f"\n  Created merchant id={mid}")

        # READ
        row = (
            await session.execute(select(Merchant).where(Merchant.id == mid))
        ).scalar_one_or_none()
        assert row is not None, f"Could not re-fetch merchant {mid}"
        assert row.domain_url == test_url
        print(f"  Read  domain_url={row.domain_url!r}")

        # UPDATE
        row.domain_url = test_url + "/v2"
        await session.flush()
        updated = (
            await session.execute(select(Merchant).where(Merchant.id == mid))
        ).scalar_one()
        assert updated.domain_url == test_url + "/v2"
        print(f"  Updated domain_url={updated.domain_url!r}")

        # DELETE
        await session.execute(delete(Merchant).where(Merchant.id == mid))
        await session.commit()

    async with initialised_db() as session:
        gone = (
            await session.execute(select(Merchant).where(Merchant.id == mid))
        ).scalar_one_or_none()
        assert gone is None, f"Merchant {mid} still present after DELETE"

    print("  [PASS] CRUD lifecycle complete.")


@pytest.mark.asyncio
async def test_merchant_domain_url_is_unique(initialised_db):
    """
    The upsert in orchestrator._persist_scan relies on a unique constraint over
    domain_url. Assert the constraint is actually present in the live schema.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from razorshield_backend.db.models import Merchant

    url = f"https://dupe-{uuid.uuid4().hex[:8]}.example.com"
    try:
        async with initialised_db() as session:
            for _ in range(2):
                await session.execute(
                    pg_insert(Merchant)
                    .values(domain_url=url)
                    .on_conflict_do_nothing(index_elements=[Merchant.domain_url])
                )
            await session.commit()

        async with initialised_db() as session:
            count = (
                await session.execute(
                    select(Merchant).where(Merchant.domain_url == url)
                )
            ).scalars().all()

        assert len(count) == 1, (
            f"Expected exactly 1 merchant row for {url}, found {len(count)} — "
            "the unique constraint on domain_url is missing, so concurrent scans "
            "of the same merchant will create duplicates."
        )
        print(f"\n  [PASS] domain_url uniqueness enforced ({len(count)} row).")
    finally:
        async with initialised_db() as session:
            await session.execute(delete(Merchant).where(Merchant.domain_url == url))
            await session.commit()


@pytest.mark.asyncio
async def test_prohibited_pattern_vector_seed(initialised_db):
    """
    Insert a real 768-dim embedding into prohibited_patterns, then query its
    self-distance via the <=> cosine operator. Self-distance must be ≈ 0.

    Previously the row was only flush()ed — never committed — and then read back
    over a *different* asyncpg connection, which cannot see another transaction's
    uncommitted rows. The query returned no rows and the test failed on
    `assert row is not None`. The write is now committed before it is read.
    """
    import asyncio

    from sentence_transformers import SentenceTransformer

    from razorshield_backend.db.models import ProhibitedPattern

    test_text = "unregistered pharmaceutical opioid controlled substance"
    model = SentenceTransformer("BAAI/bge-base-en-v1.5")

    def _encode():
        return model.encode([test_text], normalize_embeddings=True)[0].tolist()

    embedding = await asyncio.to_thread(_encode)
    assert len(embedding) == VECTOR_DIM, f"Embedding dim={len(embedding)}, expected {VECTOR_DIM}"

    pattern_id = None
    try:
        # 1. Insert AND COMMIT so the row is visible to subsequent statements.
        async with initialised_db() as session:
            pattern = ProhibitedPattern(
                category="TEST_PHARMA",
                pattern_text=test_text,
                embedding=embedding,
            )
            session.add(pattern)
            await session.flush()
            pattern_id = pattern.id
            await session.commit()

        assert pattern_id is not None
        print(f"\n  Inserted ProhibitedPattern id={pattern_id}")

        # 2. Read it back and measure self-distance.
        literal = to_vector_literal(embedding)
        async with initialised_db() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT (embedding <=> '{literal}'::vector)::float8 AS dist "
                        f"FROM prohibited_patterns WHERE id = :pid"
                    ),
                    {"pid": pattern_id},
                )
            ).fetchone()

        assert row is not None, (
            "Self-similarity query returned no rows — the committed pattern row "
            "was not visible to the reading session."
        )
        dist = float(row[0])
        assert dist < 0.01, f"Self-cosine distance too large: {dist:.8f} (expected < 0.01)"
        print(f"  [PASS] Self-cosine distance = {dist:.8f} ≈ 0")

    finally:
        if pattern_id is not None:
            async with initialised_db() as session:
                await session.execute(
                    delete(ProhibitedPattern).where(ProhibitedPattern.id == pattern_id)
                )
                await session.commit()
