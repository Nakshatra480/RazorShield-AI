"""
razorshield_backend/main.py
────────────────────────────
FastAPI application entry point for RazorShield AI.

Startup lifecycle:
  1. init_db()              — enable pgvector + auto-create tables
  2. BrowserManager.init() — launch Playwright Chromium singleton

Shutdown lifecycle:
  1. BrowserManager.close() — gracefully close Playwright

Endpoints:
  POST /api/v1/inspect              → full async merchant inspection
  GET  /api/v1/scans/{scan_id}     → retrieve past scan from DB
  POST /api/v1/benchmark/run       → trigger benchmark evaluation
  GET  /api/v1/health              → liveness probe

Run:
  uvicorn razorshield_backend.main:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field

from razorshield_backend.agents.orchestrator import run_full_inspection
from razorshield_backend.config import get_settings
from razorshield_backend.db.database import async_session_maker, init_db
from razorshield_backend.db.models import Scan
from razorshield_backend.scrapers.browser import BrowserManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Startup and shutdown lifecycle manager."""
    settings = get_settings()
    logger.info("RazorShield AI backend starting on %s", settings.openrouter_base_url)

    # Initialise DB (creates tables + pgvector extension)
    await init_db()

    # Warm up Playwright browser
    await BrowserManager.initialize()

    yield  # application runs

    # Graceful shutdown
    await BrowserManager.close()
    logger.info("RazorShield AI backend stopped.")


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="RazorShield AI API",
    description="Autonomous multi-agent merchant onboarding risk inspector.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS — allow Next.js dev server and any Vercel deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://*.vercel.app",
        "https://razorshield.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Global exception handlers ────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "status_code": 500,
        },
    )


# ─── Request / Response models ────────────────────────────────────────────────

class InspectRequest(BaseModel):
    url: str = Field(
        ...,
        description="Merchant website URL to inspect.",
        examples=["https://example-merchant.com"],
    )


class DomainInfoResponse(BaseModel):
    domain: str
    domain_age_days: int
    is_ssl_valid: bool
    ssl_expiry_days: int
    registrar: str
    registration_date: Optional[str]


class PolicyResultResponse(BaseModel):
    is_compliant: bool
    policy_score: float
    missing_disclosures: list[str]


class FlaggedItemResponse(BaseModel):
    product_title: str
    matched_category: str
    matched_pattern: str
    similarity_score: float


class CatalogResultResponse(BaseModel):
    has_prohibited_items: bool
    catalog_score: float
    checked_via_vectors: bool
    flagged_items: list[FlaggedItemResponse]


class ScanResponse(BaseModel):
    scan_id: str
    merchant_id: str
    domain: str
    risk_score: float
    risk_tier: str
    domain_info: DomainInfoResponse
    policy_result: PolicyResultResponse
    catalog_result: CatalogResultResponse
    findings: dict[str, Any]
    audit_trail: str
    guardrail_triggered: bool
    guardrail_reason: Optional[str]
    processing_time_ms: int
    created_at: str


class BenchmarkStatusResponse(BaseModel):
    status: str
    message: str
    metrics: Optional[dict[str, Any]] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Liveness probe — returns immediately."""
    return {"status": "ok", "service": "razorshield-ai"}


@app.post(
    "/api/v1/inspect",
    response_model=ScanResponse,
    status_code=status.HTTP_200_OK,
    tags=["inspection"],
    summary="Run a full multi-agent merchant risk inspection.",
)
async def inspect_merchant(body: InspectRequest) -> ScanResponse:
    """
    Triggers the full RazorShield AI pipeline:

    1. Playwright scrapes homepage, policy pages, and product catalog.
    2. WHOIS + SSL domain inspection runs concurrently.
    3. Policy Compliance Agent evaluates legal disclosures (LLM via OpenRouter).
    4. Catalog Safety Agent checks products against prohibited patterns (pgvector).
    5. Orchestrator applies guardrails, computes weighted risk score, and
       generates a human-readable audit narrative.
    6. Results are persisted to Neon PostgreSQL.

    Returns a structured `ScanResponse` with risk tier, score, and full findings.
    """
    url = str(body.url).rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        report = await run_full_inspection(url)
    except Exception as exc:
        logger.exception("Inspection failed for %s", url)
        raise HTTPException(
            status_code=500,
            detail=f"Inspection pipeline failed: {exc}",
        )

    return ScanResponse(
        scan_id=report.scan_id,
        merchant_id=report.merchant_id,
        domain=report.domain,
        risk_score=report.risk_score,
        risk_tier=report.risk_tier,
        domain_info=DomainInfoResponse(**report.domain_info),
        policy_result=PolicyResultResponse(**report.policy_result),
        catalog_result=CatalogResultResponse(
            has_prohibited_items=report.catalog_result["has_prohibited_items"],
            catalog_score=report.catalog_result["catalog_score"],
            checked_via_vectors=report.catalog_result["checked_via_vectors"],
            flagged_items=[
                FlaggedItemResponse(**fi)
                for fi in report.catalog_result["flagged_items"]
            ],
        ),
        findings=report.findings,
        audit_trail=report.audit_trail,
        guardrail_triggered=report.guardrail_triggered,
        guardrail_reason=report.guardrail_reason,
        processing_time_ms=report.processing_time_ms,
        created_at=report.created_at,
    )


@app.get(
    "/api/v1/scans/{scan_id}",
    tags=["inspection"],
    summary="Retrieve a past scan result by ID.",
)
async def get_scan(scan_id: str) -> dict[str, Any]:
    """
    Fetches a previously completed inspection from the Neon database by scan UUID.
    Returns full findings JSON and audit trail.
    """
    try:
        scan_uuid = UUID(scan_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scan ID format: {scan_id!r}. Must be a valid UUID.",
        )

    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(
            select(Scan).where(Scan.id == scan_uuid)
        )
        scan = result.scalar_one_or_none()

    if scan is None:
        raise HTTPException(
            status_code=404,
            detail=f"Scan {scan_id} not found.",
        )

    return {
        "scan_id": str(scan.id),
        "merchant_id": str(scan.merchant_id),
        "risk_score": scan.overall_risk_score,
        "risk_tier": scan.risk_tier.value,
        "findings": scan.findings_json,
        "audit_trail": scan.audit_trail,
        "created_at": scan.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.post(
    "/api/v1/benchmark/run",
    response_model=BenchmarkStatusResponse,
    tags=["benchmark"],
    summary="Trigger the full synthetic benchmark evaluation.",
)
async def run_benchmark_endpoint() -> BenchmarkStatusResponse:
    """
    Runs the full 50-merchant benchmark evaluation in the background:
      - Seeds prohibited patterns into pgvector.
      - Scores 35 synthetic safe + 15 high-risk merchant profiles.
      - Computes precision, recall, F1, and false-positive cost.
      - Writes results to `public/benchmark_results.json`.

    This endpoint is non-blocking — it returns immediately and runs in background.
    Poll GET /api/v1/health or check `public/benchmark_results.json` for completion.
    """
    from razorshield_backend.benchmark import run_benchmark

    async def _run() -> None:
        try:
            await run_benchmark()
            logger.info("Benchmark completed successfully.")
        except Exception as exc:
            logger.error("Benchmark failed: %s", exc)

    # Fire-and-forget background task
    asyncio.create_task(_run())

    return BenchmarkStatusResponse(
        status="running",
        message=(
            "Benchmark evaluation started in background. "
            "Results will be written to public/benchmark_results.json. "
            "Estimated completion: 2–5 minutes depending on OpenRouter latency."
        ),
    )
