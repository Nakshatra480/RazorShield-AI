"""
tests/conftest.py
─────────────────────────────────────────────────────────────────────────────
Shared pytest fixtures for RazorShield AI.

Sets RAZORSHIELD_TESTING=1 before any backend module is imported so that
database.py creates a NullPool engine — this prevents asyncpg connection-pool
teardown from racing against pytest's per-function event loop teardown.
"""

import os
import sys

# ── MUST be set before any razorshield_backend import ─────────────────────────
os.environ["RAZORSHIELD_TESTING"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pytest_asyncio


# ── Environment capability probes ─────────────────────────────────────────────
#
# The suite exercises real infrastructure (Neon, OpenRouter, the public web).
# Tests that need a dependency skip when it is genuinely unavailable, so an
# expired API key or an offline laptop produces "skipped", not a red build that
# hides real regressions. Availability is probed once per session.

# pytest-asyncio 1.x runs each test in its own event loop, so a session-scoped
# async fixture is not permitted. Results are memoised in this dict instead, which
# gives the same "probe once per run" behaviour with function-scoped fixtures.
_probe_cache: dict[str, bool] = {}


@pytest_asyncio.fixture
async def llm_available() -> bool:
    """True when the configured LLM provider actually answers a request."""
    if "llm" not in _probe_cache:
        from razorshield_backend.agents.llm import LLMClient
        from razorshield_backend.config import get_settings

        health = await LLMClient(get_settings()).probe()
        _probe_cache["llm"] = health.available
        if not health.available:
            print(f"\n[env] LLM unavailable — {health.detail}")
    return _probe_cache["llm"]


@pytest_asyncio.fixture
async def db_available() -> bool:
    """True when the configured PostgreSQL instance is reachable."""
    if "db" not in _probe_cache:
        from razorshield_backend.db.database import check_connection

        try:
            await check_connection()
            _probe_cache["db"] = True
        except Exception as exc:  # noqa: BLE001
            print(f"\n[env] Database unavailable — {exc}")
            _probe_cache["db"] = False
    return _probe_cache["db"]


@pytest_asyncio.fixture
async def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL is not reachable — set DATABASE_URL to run DB tests.")


@pytest_asyncio.fixture
async def initialised_db(require_db: None):
    """Ensure pgvector + tables exist, then hand back the session factory."""
    from razorshield_backend.db.database import async_session_maker, init_db

    await init_db()
    return async_session_maker


@pytest_asyncio.fixture
async def api_client():
    """
    httpx client bound to the FastAPI app **with the lifespan running**.

    ASGITransport alone does not execute startup/shutdown events, so the
    previous fixture exercised endpoints against a process where init_db() and
    BrowserManager.initialize() had never run — the inspect endpoint only worked
    because it lazily launched a browser as a side effect, and the concurrency
    semaphore was never created at all.
    """
    from httpx import ASGITransport, AsyncClient

    from razorshield_backend.main import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            timeout=200.0,
        ) as client:
            yield client


# ── Synthetic data fixtures (sync — safe at any scope) ────────────────────────

@pytest.fixture
def safe_scrape_result():
    """Fully-compliant, safe synthetic merchant scrape result."""
    from razorshield_backend.scrapers.browser import (
        MerchantScrapeResult, PolicyTexts, ProductItem,
    )
    return MerchantScrapeResult(
        url="https://safe-merchant.example.com",
        title="Safe Merchant Co.",
        meta_description="Quality goods for everyday life.",
        homepage_text="Welcome to Safe Merchant Co. We sell organic, eco-friendly products.",
        policy_texts=PolicyTexts(
            terms=(
                "SafeMerchant Ltd, registered company no. 12345678. "
                "Returns accepted within 30 days. Prohibited uses: illegal activity."
            ),
            privacy=(
                "We collect your name and email to process orders. "
                "Data is stored securely and never sold. You may opt out at any time."
            ),
            refund=(
                "Full refund within 30 days. No questions asked. "
                "Contact support@safemerchant.example.com."
            ),
            contact="Email: support@safemerchant.example.com | Phone: +1-800-555-0100",
        ),
        products=[
            ProductItem(title="Organic Cotton T-Shirt", description="100% organic", price="$29.99"),
            ProductItem(title="Bamboo Cutting Board", description="Eco kitchen tool", price="$24.99"),
            ProductItem(title="Stainless Steel Bottle", description="BPA-free 750ml", price="$19.99"),
        ],
        error=None,
    )


@pytest.fixture
def prohibited_scrape_result():
    """Synthetic merchant with explicitly prohibited products."""
    from razorshield_backend.scrapers.browser import (
        MerchantScrapeResult, PolicyTexts, ProductItem,
    )
    return MerchantScrapeResult(
        url="https://bad-actor.example.com",
        title="Discount Pharma Mart",
        meta_description="Best prices on prescription drugs.",
        homepage_text="Buy cheap drugs online. No prescription required. Best counterfeit watches.",
        policy_texts=PolicyTexts(terms="", privacy="", refund="", contact=""),
        products=[
            ProductItem(
                title="Oxycodone 80mg No Prescription Required",
                description="Unregistered pharmaceutical controlled substance opioid",
                price="$4.99",
            ),
            ProductItem(
                title="Replica Rolex AAA Grade Counterfeit",
                description="High quality fake designer knockoff imitation brand watch",
                price="$89.00",
            ),
            ProductItem(
                title="Assault Rifle Full-Auto Conversion Kit",
                description="Unlicensed firearm modification accessory ammunition",
                price="$199.00",
            ),
        ],
        error=None,
    )


@pytest.fixture
def newborn_domain_info():
    """DomainInspection for a 1-day-old domain — triggers Guardrail A."""
    from razorshield_backend.scrapers.whois_client import DomainInspection
    return DomainInspection(
        domain="brand-new-scam.xyz",
        domain_age_days=1,
        is_ssl_valid=False,
        ssl_expiry_days=-1,
        registrar="NameSilo, LLC",
        registration_date="2026-09-04T00:00:00Z",
    )


@pytest.fixture
def established_domain_info():
    """DomainInspection for a mature, trusted 27-year-old domain."""
    from razorshield_backend.scrapers.whois_client import DomainInspection
    return DomainInspection(
        domain="example.com",
        domain_age_days=9875,
        is_ssl_valid=True,
        ssl_expiry_days=90,
        registrar="ICANN",
        registration_date="1999-06-11T00:00:00Z",
    )
