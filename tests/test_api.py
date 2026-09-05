"""
tests/test_api.py
─────────────────────────────────────────────────────────────────────────────
FastAPI REST endpoint tests via httpx.AsyncClient + ASGITransport.

No external HTTP — the app runs in-process via ASGI.
All endpoints are called with real request/response cycles.
"""

import pytest


# The `api_client` fixture in conftest.py drives the app *with* its lifespan, so
# startup (init_db, Playwright launch, concurrency semaphore) actually runs.
# Plain ASGITransport skips lifespan events entirely.
@pytest.fixture
def client(api_client):
    return api_client


# ── Health check ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /api/v1/health must return 200 with {status: 'ok'}."""
    resp = await client.get("/api/v1/health")

    print(f"\n  status={resp.status_code}  body={resp.text}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data.get("status") == "ok", f"Expected status=ok, got {data!r}"
    print("  [PASS] /api/v1/health returned 200 OK.")


# ── Scan list endpoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_scans_endpoint(client):
    """
    GET /api/v1/scans must return HTTP 200 with a JSON array.
    Each item must have the expected schema keys.
    """
    resp = await client.get("/api/v1/scans?limit=5&offset=0")

    print(f"\n  status={resp.status_code}")

    assert resp.status_code == 200, (
        f"Expected 200 from GET /api/v1/scans, got {resp.status_code}\n"
        f"body={resp.text[:400]}"
    )
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"

    if len(data) > 0:
        item = data[0]
        required_keys = {"scan_id", "domain", "risk_score", "risk_tier", "created_at"}
        missing = required_keys - set(item.keys())
        assert not missing, f"Scan list item missing keys: {missing}\nitem={item!r}"
        print(f"  [PASS] GET /api/v1/scans returned {len(data)} records with correct schema.")
    else:
        print("  [INFO] No scans in DB yet — list is empty (schema valid).")


# ── Full Inspect endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_inspect_endpoint_safe_domain(client):
    """
    POST /api/v1/inspect with https://example.com.

    Asserts:
      - HTTP 200
      - Response body contains: scan_id, risk_score (float), risk_tier (string),
        audit_trail (non-empty), domain, domain_info, policy_result, catalog_result
      - risk_score is in [0, 100]
      - risk_tier is one of SAFE / MANUAL_REVIEW / HIGH_RISK
      - audit_trail has at least 50 characters
    """
    resp = await client.post(
        "/api/v1/inspect",
        json={"url": "https://example.com"},
        timeout=120.0,
    )

    print(f"\n  status={resp.status_code}")

    assert resp.status_code == 200, (
        f"Expected 200 from POST /api/v1/inspect, got {resp.status_code}\n"
        f"body={resp.text[:600]}"
    )

    data = resp.json()
    print(f"  scan_id={data.get('scan_id')!r}")
    print(f"  domain={data.get('domain')!r}")
    print(f"  risk_score={data.get('risk_score')}")
    print(f"  risk_tier={data.get('risk_tier')!r}")
    print(f"  audit_trail_len={len(data.get('audit_trail', ''))}")
    print(f"  guardrail_triggered={data.get('guardrail_triggered')}")

    # Required keys
    required = {
        "scan_id", "risk_score", "risk_tier", "audit_trail",
        "domain", "domain_info", "policy_result", "catalog_result",
        "guardrail_triggered", "processing_time_ms",
    }
    missing = required - set(data.keys())
    assert not missing, f"Response missing required keys: {missing}"

    # Type + range validation
    assert isinstance(data["risk_score"], (int, float)), \
        f"risk_score must be numeric, got {type(data['risk_score'])}"
    assert 0 <= data["risk_score"] <= 100, \
        f"risk_score out of [0,100]: {data['risk_score']}"

    valid_tiers = {"SAFE", "MANUAL_REVIEW", "HIGH_RISK"}
    assert data["risk_tier"] in valid_tiers, \
        f"risk_tier {data['risk_tier']!r} not in {valid_tiers}"

    assert len(data.get("audit_trail", "")) >= 50, \
        f"audit_trail too short ({len(data.get('audit_trail', ''))}) — LLM narrative broken"

    # domain_info schema
    di = data["domain_info"]
    for key in ("domain_age_days", "is_ssl_valid", "ssl_expiry_days", "registrar"):
        assert key in di, f"domain_info missing key: {key!r}"

    # policy_result schema
    pr = data["policy_result"]
    for key in ("is_compliant", "policy_score", "missing_disclosures"):
        assert key in pr, f"policy_result missing key: {key!r}"
    assert 0.0 <= pr["policy_score"] <= 1.0, \
        f"policy_score out of range: {pr['policy_score']}"

    # catalog_result schema
    cr = data["catalog_result"]
    for key in ("has_prohibited_items", "catalog_score", "flagged_items"):
        assert key in cr, f"catalog_result missing key: {key!r}"

    print(f"  [PASS] POST /api/v1/inspect returned valid full report for example.com")
    print(f"         risk={data['risk_score']:.1f} ({data['risk_tier']}) "
          f"in {data['processing_time_ms']}ms")


@pytest.mark.asyncio
async def test_inspect_endpoint_invalid_url(client):
    """
    POST /api/v1/inspect with a malformed URL must return HTTP 422 (validation error).
    """
    resp = await client.post(
        "/api/v1/inspect",
        json={"url": "not-a-url"},
        timeout=30.0,
    )
    print(f"\n  status={resp.status_code}  body={resp.text[:200]}")

    assert resp.status_code in (400, 422), (
        f"Expected 400 or 422 for invalid URL, got {resp.status_code}"
    )
    print("  [PASS] Invalid URL correctly rejected with 4xx.")


@pytest.mark.asyncio
async def test_inspect_endpoint_missing_body(client):
    """
    POST /api/v1/inspect with no body must return HTTP 422.
    """
    resp = await client.post("/api/v1/inspect", content=b"", timeout=10.0)
    print(f"\n  status={resp.status_code}")
    assert resp.status_code == 422, \
        f"Expected 422 for empty body, got {resp.status_code}"
    print("  [PASS] Missing body correctly rejected with 422.")


# ── Benchmark trigger endpoint ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_run_endpoint(client):
    """
    POST /api/v1/benchmark/run must return HTTP 200 with a status message.
    Asserts that the response contains a 'status' field.
    Does NOT wait for the benchmark to complete — just verifies the trigger works.
    """
    resp = await client.post("/api/v1/benchmark/run", timeout=30.0)

    print(f"\n  status={resp.status_code}  body={resp.text[:300]}")

    assert resp.status_code == 200, (
        f"Expected 200 from POST /api/v1/benchmark/run, got {resp.status_code}\n"
        f"body={resp.text[:400]}"
    )
    data = resp.json()
    assert "status" in data, f"Response missing 'status' key: {data!r}"
    assert "message" in data, f"Response missing 'message' key: {data!r}"
    print(f"  [PASS] POST /api/v1/benchmark/run returned: {data}")


# ── Readiness probe ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_readiness_endpoint_reports_components(client):
    """
    GET /api/v1/readiness must report per-dependency status.

    It returns 200 even when a dependency is down (status="degraded") so the UI
    can render real state; a non-200 would just look like "backend offline".
    """
    resp = await client.get("/api/v1/readiness")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"

    data = resp.json()
    assert data["status"] in ("ok", "degraded"), f"Unexpected status: {data['status']!r}"

    components = data.get("components", {})
    for name in ("database", "browser", "llm"):
        assert name in components, f"readiness missing component: {name!r}"
        assert "status" in components[name], f"component {name} has no status"

    print(f"\n  overall={data['status']}")
    for name, comp in components.items():
        print(f"    {name}: {comp['status']} {comp.get('detail') or ''}")
    print("  [PASS] /api/v1/readiness reported all components.")


# ── Pagination validation ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query,expected",
    [
        ("?limit=0", 422),        # below minimum
        ("?limit=500", 422),      # above the 200 cap
        ("?offset=-1", 422),      # negative offset would break the SQL
        ("?limit=5&offset=0", 200),
    ],
)
@pytest.mark.asyncio
async def test_list_scans_validates_pagination(client, query, expected):
    """
    Out-of-range pagination must be rejected by validation, not passed to SQL.
    Previously `limit` was only clamped with min(limit, 200) and `offset` was
    unchecked, so `?offset=-1` reached Postgres and raised a 500.
    """
    resp = await client.get(f"/api/v1/scans{query}")
    assert resp.status_code == expected, (
        f"GET /api/v1/scans{query} → {resp.status_code}, expected {expected}\n"
        f"body={resp.text[:300]}"
    )
    print(f"\n  [PASS] /api/v1/scans{query} → {resp.status_code}")


# ── Scan detail endpoint ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_scan_rejects_malformed_uuid(client):
    """A non-UUID scan id must return 400, not 500."""
    resp = await client.get("/api/v1/scans/not-a-uuid")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text[:200]}"
    print(f"\n  [PASS] Malformed scan id rejected with 400.")


@pytest.mark.asyncio
async def test_get_scan_returns_404_for_unknown_id(client):
    """A well-formed but unknown scan id must return 404."""
    import uuid

    resp = await client.get(f"/api/v1/scans/{uuid.uuid4()}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text[:200]}"
    print("  [PASS] Unknown scan id returned 404.")


@pytest.mark.asyncio
async def test_get_scan_round_trip_includes_domain(client):
    """
    A scan fetched by id must identify its merchant.

    The detail endpoint previously returned no domain at all, so a client that
    followed a scan_id from /api/v1/scans could not tell which merchant the
    record described.
    """
    listing = await client.get("/api/v1/scans?limit=1")
    assert listing.status_code == 200
    rows = listing.json()
    if not rows:
        pytest.skip("No scans in the database yet — nothing to round-trip.")

    scan_id = rows[0]["scan_id"]
    resp = await client.get(f"/api/v1/scans/{scan_id}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"

    data = resp.json()
    for key in ("scan_id", "domain", "risk_score", "risk_tier", "findings", "audit_trail"):
        assert key in data, f"Scan detail missing key: {key!r}"
    assert data["domain"], "Scan detail returned an empty domain"
    print(f"\n  [PASS] Scan {scan_id[:8]}… resolved to domain {data['domain']!r}")
