"""
tests/test_config.py
─────────────────────────────────────────────────────────────────────────────
Settings and connection-string handling. Pure unit tests — no I/O.
"""

import pytest

from razorshield_backend.db.database import _build_async_db_url, redact_db_url


# ── Connection string normalisation ───────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        # Neon hands out both of these parameters; asyncpg accepts neither.
        (
            "postgresql://u:p@h/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@h/db",
        ),
        # Reversed order previously left a dangling separator behind.
        (
            "postgresql://u:p@h/db?channel_binding=require&sslmode=require",
            "postgresql+asyncpg://u:p@h/db",
        ),
        # `postgres://` is what most dashboards copy out. The old string-replace
        # only matched "postgresql://", so this URL silently kept a scheme
        # SQLAlchemy could not resolve to the asyncpg driver.
        ("postgres://u:p@h/db?sslmode=require", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        # Already-async URLs pass through, minus unsupported params.
        ("postgresql+asyncpg://u:p@h/db?sslmode=require", "postgresql+asyncpg://u:p@h/db"),
        # Supported params must be preserved.
        (
            "postgresql://u:p@h/db?application_name=rs&sslmode=require",
            "postgresql+asyncpg://u:p@h/db?application_name=rs",
        ),
    ],
)
def test_build_async_db_url(raw, expected):
    assert _build_async_db_url(raw) == expected


def test_build_async_db_url_never_leaves_dangling_separator():
    """Whatever the parameter order, the result must be a clean URL."""
    for raw in (
        "postgresql://u:p@h/db?channel_binding=require",
        "postgresql://u:p@h/db?sslmode=require",
        "postgresql://u:p@h/db?sslmode=require&channel_binding=require&gssencmode=disable",
    ):
        out = _build_async_db_url(raw)
        assert not out.endswith(("?", "&")), f"dangling separator in {out!r}"
        assert "?&" not in out and "&&" not in out, f"malformed query in {out!r}"


@pytest.mark.parametrize("bad", ["", "   ", "mysql://u:p@h/db", "redis://h:6379"])
def test_build_async_db_url_rejects_invalid(bad):
    """A misconfigured DATABASE_URL must fail loudly at import, not at query time."""
    with pytest.raises(ValueError):
        _build_async_db_url(bad)


def test_redact_db_url_hides_password():
    """Connection strings get logged; the password must never appear."""
    redacted = redact_db_url("postgresql://neondb_owner:npg_supersecret@ep-x.neon.tech/neondb")
    assert "npg_supersecret" not in redacted
    assert "neondb_owner" in redacted
    assert "***" in redacted


# ── Settings ──────────────────────────────────────────────────────────────────

def test_settings_expose_operational_limits():
    """
    The knobs the API relies on must exist with usable defaults. `max_concurrent_
    inspections` in particular was previously declared but never applied.
    """
    from razorshield_backend.config import get_settings

    s = get_settings()
    assert s.max_concurrent_inspections >= 1
    assert s.inspection_timeout_seconds > 0
    assert s.llm_timeout_seconds > 0
    assert s.llm_max_attempts >= 1
    assert s.max_products_per_scan >= 1
    assert 0.0 <= s.prohibited_similarity_threshold <= 1.0
    assert s.embedding_dimensions == 768, (
        "embedding_dimensions must match Vector(768) on ProhibitedPattern.embedding"
    )


def test_cors_origin_list_is_parsed():
    from razorshield_backend.config import get_settings

    origins = get_settings().cors_origin_list
    assert isinstance(origins, list)
    assert all(o and not o.isspace() for o in origins), f"blank origin in {origins}"
    assert not any("*" in o for o in origins), (
        "Wildcard origins do not work in Starlette's allow_origins (exact match "
        "only) — they belong in cors_allow_origin_regex."
    )


def test_vercel_preview_origin_matches_cors_regex():
    """
    Preview deployments must be admitted by the regex.

    The previous config listed the literal string "https://*.vercel.app" in
    allow_origins, which Starlette compares by exact equality — so every Vercel
    preview deployment was silently blocked by CORS.
    """
    import re

    from razorshield_backend.config import get_settings

    pattern = get_settings().cors_allow_origin_regex
    assert pattern, "No CORS regex configured for preview deployments"
    compiled = re.compile(pattern)
    assert compiled.fullmatch("https://razorshield-ai-git-main.vercel.app")
    assert not compiled.fullmatch("https://evil.com")


def test_embedding_dimension_matches_orm_column():
    """Config and schema must agree, or every pgvector comparison errors out."""
    from razorshield_backend.config import get_settings
    from razorshield_backend.db.models import ProhibitedPattern

    column = ProhibitedPattern.__table__.c.embedding
    assert column.type.dim == get_settings().embedding_dimensions
