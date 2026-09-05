"""
razorshield_backend/main.py
────────────────────────────
FastAPI application entry point for RazorShield AI.

Startup lifecycle:
  1. init_db()              — enable pgvector + auto-create tables
  2. BrowserManager.initialize() — launch Playwright Chromium singleton

Shutdown lifecycle:
  1. BrowserManager.close()  — gracefully close Playwright
  2. dispose_engine()        — drain the database pool

Endpoints:
  POST /api/v1/inspect              → full async merchant inspection
  GET  /api/v1/scans                → paginated scan history
  GET  /api/v1/scans/{scan_id}      → retrieve past scan from DB
  POST /api/v1/benchmark/run        → trigger benchmark evaluation
  GET  /api/v1/benchmark/status     → benchmark progress
  GET  /api/v1/health               → liveness probe
  GET  /api/v1/readiness            → dependency health (DB, browser, LLM)

Run:
  uvicorn razorshield_backend.main:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field

from razorshield_backend.agents.orchestrator import get_llm_client, run_full_inspection
from razorshield_backend.config import get_settings
from razorshield_backend.db.database import (
    async_session_maker,
    check_connection,
    dispose_engine,
    init_db,
)
from razorshield_backend.db.models import Merchant, Scan
from razorshield_backend.scrapers.browser import BrowserManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

API_VERSION = "1.0.0"

# Admits at most `max_concurrent_inspections` scans at a time. Each inspection
# holds a browser context, an embedding batch, and DB connections, so unbounded
# concurrency exhausts the pool and the LLM quota. Created during startup, when
# the running loop exists.
_inspection_semaphore: Optional[asyncio.Semaphore] = None

# Strong references to fire-and-forget tasks. asyncio only holds a weak
# reference to a running task, so a bare `create_task(...)` whose result is
# discarded can be garbage-collected mid-flight — the benchmark could silently
# stop partway through.
_background_tasks: set[asyncio.Task] = set()

# Guards against a second benchmark starting while one is already running:
# they both write public/benchmark_results.json and both re-seed the shared
# prohibited_patterns table.
_benchmark_lock = asyncio.Lock()
_benchmark_state: dict[str, Any] = {"status": "idle", "message": "No benchmark has been run yet."}


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Startup and shutdown lifecycle manager."""
    global _inspection_semaphore

    settings = get_settings()
    logger.info(
        "RazorShield AI %s starting (env=%s, model=%s)",
        API_VERSION,
        settings.environment,
        settings.llm_model,
    )

    _inspection_semaphore = asyncio.Semaphore(settings.max_concurrent_inspections)

    # Startup must not hard-fail on a transient dependency outage — the process
    # should come up and report "degraded" via /readiness instead of crash-looping.
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        logger.error("Database initialisation failed at startup: %s", exc)

    try:
        await BrowserManager.initialize()
    except Exception as exc:  # noqa: BLE001
        logger.error("Playwright initialisation failed at startup: %s", exc)

    try:
        yield  # application runs
    finally:
        for task in list(_background_tasks):
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)

        await BrowserManager.close()
        await dispose_engine()
        logger.info("RazorShield AI backend stopped.")


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="RazorShield AI API",
    description="Autonomous multi-agent merchant onboarding risk inspector.",
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

_settings = get_settings()

# CORS — exact origins plus a regex for preview deployments.
# Starlette matches `allow_origins` by exact string, so a literal
# "https://*.vercel.app" entry never matches anything; wildcard subdomains must
# go through allow_origin_regex.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_origin_regex=_settings.cors_allow_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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
    body: dict[str, Any] = {"error": "Internal server error", "status_code": 500}
    # Raw exception text can carry connection strings, file paths, and provider
    # payloads — useful locally, an information leak in production.
    if not _settings.is_production:
        body["detail"] = str(exc)
    return JSONResponse(status_code=500, content=body)


# ─── Request / Response models ────────────────────────────────────────────────

class InspectRequest(BaseModel):
    url: AnyHttpUrl = Field(
        ...,
        description="Merchant website URL to inspect (must start with http:// or https://).",
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
    evaluated_by: str = "llm"
    agent_error: Optional[str] = None
    # True when the site blocked inspection, so policy_score carries no meaning
    # and was excluded from the weighted risk score.
    inconclusive: bool = False


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
    agent_error: Optional[str] = None


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
    # Lets the UI label a verdict that ran without the LLM / without pgvector.
    fully_analyzed: bool = True
    llm_narrative: bool = False


class BenchmarkStatusResponse(BaseModel):
    status: str
    message: str
    metrics: Optional[dict[str, Any]] = None


class ComponentHealth(BaseModel):
    status: str
    detail: Optional[str] = None
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    # LLM only: credential failover state. Keys are redacted — never returned
    # in full, since /readiness is reachable by the browser.
    keys: Optional[list[dict[str, Any]]] = None
    active_key: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: str
    service: str
    version: str
    components: dict[str, ComponentHealth]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe — returns immediately without touching dependencies.
    Use /api/v1/readiness to check whether those dependencies are usable.
    """
    return {"status": "ok", "service": "razorshield-ai", "version": API_VERSION}


@app.get("/api/v1/readiness", response_model=ReadinessResponse, tags=["system"])
async def readiness_check() -> ReadinessResponse:
    """
    Dependency probe: reports live status for PostgreSQL, the Playwright browser
    pool, and the LLM provider. Returns 200 with status="degraded" when a
    dependency is down, so the UI can show real state rather than a static badge.
    """
    components: dict[str, ComponentHealth] = {}

    # Database
    try:
        latency = await asyncio.wait_for(check_connection(), timeout=8)
        components["database"] = ComponentHealth(status="ok", latency_ms=round(latency, 2))
    except Exception as exc:  # noqa: BLE001
        components["database"] = ComponentHealth(status="down", detail=str(exc)[:200])

    # Playwright
    try:
        healthy = await BrowserManager.is_healthy()
        components["browser"] = ComponentHealth(
            status="ok" if healthy else "down",
            detail=None if healthy else "Chromium not launched",
        )
    except Exception as exc:  # noqa: BLE001
        components["browser"] = ComponentHealth(status="down", detail=str(exc)[:200])

    # LLM — reuses the shared circuit-breaker state, so polling this endpoint
    # does not burn provider quota on every request.
    llm = get_llm_client(_settings)
    cached = llm.health
    key_status = llm.key_status()
    active = next((k["label"] for k in key_status if k["active"]), None)

    if cached is None:
        components["llm"] = ComponentHealth(
            status="unknown",
            model=_settings.llm_model,
            detail=f"Not yet exercised ({llm.key_count} key(s) configured)",
            keys=key_status,
            active_key=active,
        )
    else:
        components["llm"] = ComponentHealth(
            status="ok" if cached.available else "unavailable",
            model=_settings.llm_model,
            detail=None if cached.available else cached.detail,
            keys=key_status,
            active_key=active,
        )

    overall = "ok" if all(c.status == "ok" for c in components.values()) else "degraded"
    return ReadinessResponse(
        status=overall,
        service="razorshield-ai",
        version=API_VERSION,
        components=components,
    )


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
    3. Policy Compliance Agent evaluates legal disclosures (LLM, with a
       deterministic rubric fallback when the provider is unavailable).
    4. Catalog Safety Agent checks products against prohibited patterns (pgvector).
    5. Orchestrator applies guardrails, computes weighted risk score, and
       generates a human-readable audit narrative.
    6. Results are persisted to Neon PostgreSQL.

    Returns a structured `ScanResponse` with risk tier, score, and full findings.
    """
    url = str(body.url).rstrip("/")

    # AnyHttpUrl already guarantees a scheme; reject anything that is not web
    # traffic so the scraper is never handed ftp:// or file:// style targets.
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL must use http or https.")

    if _inspection_semaphore is None:
        raise HTTPException(status_code=503, detail="Service is still starting up.")

    if _inspection_semaphore.locked():
        logger.info("Inspection queue saturated; %s is waiting for a slot.", url)

    async with _inspection_semaphore:
        try:
            report = await asyncio.wait_for(
                run_full_inspection(url),
                timeout=_settings.inspection_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error("Inspection timed out for %s", url)
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Inspection exceeded the "
                    f"{_settings.inspection_timeout_seconds:.0f}s budget for {url}."
                ),
            )
        except Exception as exc:
            logger.exception("Inspection failed for %s", url)
            detail = (
                "Inspection pipeline failed."
                if _settings.is_production
                else f"Inspection pipeline failed: {exc}"
            )
            raise HTTPException(status_code=500, detail=detail)

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
            agent_error=report.catalog_result.get("agent_error"),
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
        fully_analyzed=report.fully_analyzed,
        llm_narrative=report.llm_narrative,
    )


@app.get(
    "/api/v1/scans",
    tags=["inspection"],
    summary="List recent scan results (paginated).",
)
async def list_scans(
    limit: int = Query(default=50, ge=1, le=200, description="Rows to return (1–200)."),
    offset: int = Query(default=0, ge=0, description="Rows to skip."),
) -> list[dict[str, Any]]:
    """
    Returns a paginated list of recent merchant inspections from Neon DB,
    ordered newest-first. Used to populate the Risk Operations Feed in the UI.
    Joins with the merchants table to resolve the human-readable domain name.
    """
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(
            select(Scan, Merchant)
            .join(Merchant, Scan.merchant_id == Merchant.id)
            .order_by(Scan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = result.all()

    output = []
    for scan, merchant in rows:
        # Extract bare domain from the stored URL ("https://stripe.com" → "stripe.com")
        raw_url = merchant.domain_url or ""
        try:
            domain = urlparse(raw_url).netloc or raw_url
        except ValueError:
            domain = raw_url

        findings = scan.findings_json or {}
        scoring = findings.get("scoring") or {}
        # guardrail_triggered lives under `scoring` in the findings payload; the
        # previous top-level lookup always missed and reported False for every row.
        guardrail = bool(
            scoring.get("guardrail_triggered", findings.get("guardrail_triggered", False))
        )
        quality = findings.get("analysis_quality") or {}

        output.append({
            "scan_id": str(scan.id),
            "domain": domain,
            "risk_score": float(scan.overall_risk_score),
            "risk_tier": scan.risk_tier.value,
            "created_at": scan.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "guardrail_triggered": guardrail,
            "fully_analyzed": bool(quality.get("fully_analyzed", True)),
        })

    return output


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
            select(Scan, Merchant)
            .join(Merchant, Scan.merchant_id == Merchant.id)
            .where(Scan.id == scan_uuid)
        )
        row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found.")

    scan, merchant = row
    findings = scan.findings_json or {}
    scoring = findings.get("scoring") or {}

    return {
        "scan_id": str(scan.id),
        "merchant_id": str(scan.merchant_id),
        # The detail view previously omitted the domain entirely, so a client
        # fetching a scan by id had no way to tell which merchant it described.
        "domain": urlparse(merchant.domain_url or "").netloc or merchant.domain_url,
        "url": merchant.domain_url,
        "risk_score": float(scan.overall_risk_score),
        "risk_tier": scan.risk_tier.value,
        "guardrail_triggered": bool(scoring.get("guardrail_triggered", False)),
        "guardrail_reason": scoring.get("guardrail_reason"),
        "findings": findings,
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

    Non-blocking — returns immediately. Poll GET /api/v1/benchmark/status.
    """
    from razorshield_backend.benchmark import run_benchmark

    if _benchmark_lock.locked():
        return BenchmarkStatusResponse(
            status="running",
            message="A benchmark run is already in progress. Poll /api/v1/benchmark/status.",
        )

    async def _run() -> None:
        async with _benchmark_lock:
            _benchmark_state.update(status="running", message="Benchmark in progress…")
            try:
                results = await run_benchmark()
                _benchmark_state.update(
                    status="complete",
                    message="Benchmark completed successfully.",
                    metrics=results.get("metrics"),
                )
                logger.info("Benchmark completed successfully.")
            except asyncio.CancelledError:
                _benchmark_state.update(status="cancelled", message="Benchmark cancelled.")
                raise
            except Exception as exc:  # noqa: BLE001
                _benchmark_state.update(status="error", message=f"Benchmark failed: {exc}")
                logger.error("Benchmark failed: %s", exc)

    _spawn_background(_run())

    return BenchmarkStatusResponse(
        status="running",
        message=(
            "Benchmark evaluation started in background. "
            "Results will be written to public/benchmark_results.json. "
            "Estimated completion: 2–5 minutes depending on LLM latency."
        ),
    )


@app.get(
    "/api/v1/benchmark/status",
    response_model=BenchmarkStatusResponse,
    tags=["benchmark"],
    summary="Report the state of the most recent benchmark run.",
)
async def benchmark_status() -> BenchmarkStatusResponse:
    """Poll target for the UI while a background benchmark is running."""
    return BenchmarkStatusResponse(
        status=str(_benchmark_state.get("status", "idle")),
        message=str(_benchmark_state.get("message", "")),
        metrics=_benchmark_state.get("metrics"),
    )
