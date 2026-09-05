"""
razorshield_backend/agents/orchestrator.py
───────────────────────────────────────────
Unified risk engine: coordinates scraping, domain inspection, and sub-agents
into a final, deterministic risk verdict with a human-readable audit narrative.

Two entry points:
  1. run_full_inspection(url)        — for live API calls (scrapes in real-time)
  2. score_from_raw_data(...)        — for benchmark evaluation (inject synthetic data)

Risk scoring:
  ┌─ Guardrail A: domain_age < 3 days AND policy_score < 0.4  → HIGH_RISK (95)
  ├─ Guardrail B: has_prohibited_items = True                  → HIGH_RISK (90)
  └─ Composite: 0.4×(100 - policy_score×100)
              + 0.4×(100 - catalog_score×100)
              + 0.2×domain_risk_component

  Tier mapping:
    0 – 34  → SAFE
    35 – 64 → MANUAL_REVIEW
    65 – 100→ HIGH_RISK
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from razorshield_backend.agents.catalog_agent import CatalogAgent, CatalogResult
from razorshield_backend.agents.llm import LLMClient, LLMUnavailable
from razorshield_backend.agents.policy_agent import PolicyAgent, PolicyResult
from razorshield_backend.config import Settings, get_settings
from razorshield_backend.db.database import get_session
from razorshield_backend.db.models import Merchant, RiskTier, Scan
from razorshield_backend.scrapers.browser import (
    MerchantScrapeResult,
    scrape_merchant,
)
from razorshield_backend.scrapers.whois_client import DomainInspection, inspect_domain

logger = logging.getLogger(__name__)

# Scoring weights — kept as named constants so the audit payload and the
# computation can never drift apart.
_POLICY_WEIGHT = 0.4
_CATALOG_WEIGHT = 0.4
_DOMAIN_WEIGHT = 0.2

_GUARDRAIL_A_SCORE = 95.0
_GUARDRAIL_B_SCORE = 90.0


# ─── Shared LLM client ────────────────────────────────────────────────────────
# One client per process so the circuit breaker is shared: when the provider is
# out of credits, the first failure disables LLM calls for every agent and every
# merchant in the batch rather than each re-discovering it.
_llm_client: Optional[LLMClient] = None


def get_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(settings or get_settings())
    return _llm_client


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class ScanReport:
    """Complete result of a multi-agent merchant inspection."""
    scan_id: str
    merchant_id: str
    domain: str
    risk_score: float
    risk_tier: str
    domain_info: dict
    policy_result: dict
    catalog_result: dict
    findings: dict
    audit_trail: str
    guardrail_triggered: bool
    guardrail_reason: Optional[str]
    processing_time_ms: int
    created_at: str
    # True when the audit narrative came from the LLM rather than the template.
    llm_narrative: bool = False
    # True when every signal was produced by its primary (non-degraded) path.
    fully_analyzed: bool = True


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _compute_domain_risk(domain: DomainInspection) -> float:
    """
    Normalise domain age into a 0–100 risk component.
    Very new domains (< 30 days) are treated as high-risk signals.
    """
    if domain.domain_age_days < 0:
        return 60.0   # unknown age = elevated uncertainty
    if domain.domain_age_days < 3:
        return 100.0
    if domain.domain_age_days < 30:
        return 80.0
    if domain.domain_age_days < 180:
        return 50.0
    if domain.domain_age_days < 365:
        return 25.0
    return max(0.0, 20.0 - (domain.domain_age_days / 365) * 2)


def _determine_tier(score: float) -> RiskTier:
    if score < 35:
        return RiskTier.SAFE
    if score < 65:
        return RiskTier.MANUAL_REVIEW
    return RiskTier.HIGH_RISK


def _compute_risk_score(
    policy: PolicyResult,
    catalog: CatalogResult,
    domain: DomainInspection,
) -> tuple[float, bool, Optional[str]]:
    """
    Apply guardrails first, then compute weighted composite score.

    Returns (risk_score, guardrail_triggered, guardrail_reason).
    """
    # ── Guardrail A: brand-new domain with no compliance policies ─────────────
    if 0 <= domain.domain_age_days < 3 and policy.policy_score < 0.4:
        return _GUARDRAIL_A_SCORE, True, (
            f"Domain registered {domain.domain_age_days} day(s) ago with "
            f"policy compliance score {policy.policy_score:.2f} — automatic HIGH_RISK."
        )

    # ── Guardrail B: prohibited goods detected ────────────────────────────────
    if catalog.has_prohibited_items:
        # Sorted for a stable reason string across runs on identical input.
        categories = sorted({item.matched_category for item in catalog.flagged_items})
        return _GUARDRAIL_B_SCORE, True, (
            f"Prohibited items detected in merchant catalogue: "
            f"{', '.join(categories[:3])}."
        )

    # ── Weighted composite ────────────────────────────────────────────────────
    domain_risk = _compute_domain_risk(domain)
    catalog_component = _CATALOG_WEIGHT * (100.0 - catalog.catalog_score * 100.0)
    domain_component = _DOMAIN_WEIGHT * domain_risk

    if policy.inconclusive:
        # The site never showed us its policies (bot challenge / access denial),
        # so `policy_score` is a placeholder, not a measurement. Feeding 0.0 into
        # the average would add a flat 40-point penalty for being well defended —
        # which hits established merchants hardest, exactly backwards. Instead we
        # score on the evidence we actually have and renormalise the remaining
        # weights so they still sum to 1.
        remaining = _CATALOG_WEIGHT + _DOMAIN_WEIGHT
        risk_score = (catalog_component + domain_component) / remaining
        risk_score = max(0.0, min(100.0, risk_score))
        return risk_score, False, None

    policy_component = _POLICY_WEIGHT * (100.0 - policy.policy_score * 100.0)
    risk_score = policy_component + catalog_component + domain_component
    risk_score = max(0.0, min(100.0, risk_score))

    return risk_score, False, None


# ─── Audit narrative generator ────────────────────────────────────────────────

_AUDIT_SYSTEM_PROMPT = """You are a senior risk analyst at a payment gateway writing a formal inspection report.
Write a concise (200-300 word) plain-text audit narrative explaining the risk verdict for this merchant.
Cover: what was found during policy review, catalog check, and domain inspection.
State the risk tier and why. Do NOT use bullet points or markdown — write formal prose paragraphs."""


def _render_template_narrative(
    url: str,
    risk_score: float,
    risk_tier: RiskTier,
    domain: DomainInspection,
    policy: PolicyResult,
    catalog: CatalogResult,
    guardrail_triggered: bool,
    guardrail_reason: Optional[str],
) -> str:
    """
    Deterministic narrative used when the LLM is unavailable.

    Written as multiple sentences on separate lines because the UI renders the
    audit trail line-by-line; a single blob would collapse to one row.
    """
    flagged = ", ".join(i.product_title for i in catalog.flagged_items[:3]) or "none"
    missing = "; ".join(policy.missing_disclosures[:4]) or "none"
    age = (
        f"{domain.domain_age_days} days"
        if domain.domain_age_days >= 0
        else "unknown (WHOIS lookup failed)"
    )

    lines = [
        f"Inspection of {domain.domain} completed on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        f"Source URL: {url}.",
        f"Domain age: {age}. Registrar: {domain.registrar or 'unknown'}. "
        f"SSL certificate valid: {'yes' if domain.is_ssl_valid else 'no'}.",
        (
            "Policy compliance could not be assessed: the site blocked automated "
            f"inspection ({policy.agent_error or 'anti-bot challenge'}). The policy "
            "signal was excluded from the risk score rather than counted as a failure."
            if policy.inconclusive
            else f"Policy compliance scored {policy.policy_score:.2f} of 1.00 "
                 f"(evaluated by {policy.evaluated_by}). Missing disclosures: {missing}."
        ),
        f"Catalog safety scored {catalog.catalog_score:.2f} of 1.00 using "
        f"{'pgvector similarity search' if catalog.checked_via_vectors else 'keyword matching'}. "
        f"Flagged items: {flagged}.",
    ]
    if guardrail_triggered and guardrail_reason:
        lines.append(f"Guardrail override applied: {guardrail_reason}")
    lines.append(
        f"Final verdict: {risk_tier.value} with a composite risk score of "
        f"{risk_score:.1f} out of 100."
    )
    if policy.agent_error:
        lines.append(f"Note: {policy.agent_error}")
    if catalog.agent_error:
        lines.append(f"Note: catalog agent degraded — {catalog.agent_error}")
    return "\n".join(lines)


async def _generate_audit_narrative(
    url: str,
    risk_score: float,
    risk_tier: RiskTier,
    domain: DomainInspection,
    policy: PolicyResult,
    catalog: CatalogResult,
    guardrail_triggered: bool,
    guardrail_reason: Optional[str],
    llm: LLMClient,
) -> tuple[str, bool]:
    """
    Generate a human-readable audit narrative via LLM.
    Returns (narrative, came_from_llm) — falls back to a template on any failure.
    """
    flagged_str = ", ".join(i.product_title for i in catalog.flagged_items[:3]) or "none"
    missing_str = "; ".join(policy.missing_disclosures[:4]) or "none"

    context = (
        f"Merchant URL: {url}\n"
        f"Domain: {domain.domain} | Age: {domain.domain_age_days} days | "
        f"SSL valid: {domain.is_ssl_valid} | Registrar: {domain.registrar}\n"
        + (
            "Policy compliance: NOT ASSESSABLE — the site served an anti-bot "
            "challenge, so no policy documents could be read. Do not describe the "
            "merchant as non-compliant; say compliance is unverified.\n"
            if policy.inconclusive
            else f"Policy compliance score: {policy.policy_score:.2f} | "
                 f"Missing disclosures: {missing_str}\n"
        )
        + 
        f"Catalog safety score: {catalog.catalog_score:.2f} | "
        f"Flagged items: {flagged_str}\n"
        f"Final risk score: {risk_score:.1f}/100 | Risk tier: {risk_tier.value}\n"
        f"Guardrail triggered: {guardrail_triggered}"
        + (f" — {guardrail_reason}" if guardrail_reason else "")
    )

    try:
        narrative = await llm.complete(
            system_prompt=_AUDIT_SYSTEM_PROMPT,
            user_message=context,
            temperature=0.2,
            max_tokens=512,
        )
        return narrative, True
    except LLMUnavailable as exc:
        # Logged at INFO when the breaker is already open — this is an expected,
        # already-reported condition, not a new fault worth a warning per scan.
        logger.info("Audit narrative falling back to template: %s", exc.reason)
        return (
            _render_template_narrative(
                url, risk_score, risk_tier, domain, policy, catalog,
                guardrail_triggered, guardrail_reason,
            ),
            False,
        )


# ─── DB persistence ───────────────────────────────────────────────────────────

async def _persist_scan(
    url: str,
    risk_score: float,
    risk_tier: RiskTier,
    findings: dict,
    audit_trail: str,
) -> tuple[str, str]:
    """
    Upsert Merchant record and insert new Scan record.
    Returns (merchant_id, scan_id) as strings.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async with get_session() as session:
        # Insert-or-ignore on the unique domain_url, then read back. A plain
        # SELECT-then-INSERT races with concurrent scans of the same merchant
        # and raises a UniqueViolation; ON CONFLICT DO NOTHING makes the upsert
        # safe under the concurrency the API actually allows.
        await session.execute(
            pg_insert(Merchant)
            .values(domain_url=url)
            .on_conflict_do_nothing(index_elements=[Merchant.domain_url])
        )
        merchant = (
            await session.execute(select(Merchant).where(Merchant.domain_url == url))
        ).scalar_one()

        scan = Scan(
            merchant_id=merchant.id,
            overall_risk_score=risk_score,
            risk_tier=risk_tier,
            findings_json=findings,
            audit_trail=audit_trail,
        )
        session.add(scan)
        await session.flush()

        return str(merchant.id), str(scan.id)


# ─── Core scoring function (used by both live API and benchmark) ──────────────

async def score_from_raw_data(
    url: str,
    scrape_result: MerchantScrapeResult,
    domain_info: DomainInspection,
    *,
    persist: bool = True,
    settings: Optional[Settings] = None,
) -> ScanReport:
    """
    Run policy + catalog agents on pre-fetched data and produce a ScanReport.

    This is the central scoring function. `run_full_inspection` calls this after
    scraping. The benchmark module calls this directly with synthetic data.

    Args:
        url:           Original merchant URL.
        scrape_result: Output from browser.scrape_merchant (real or synthetic).
        domain_info:   Output from whois_client.inspect_domain (real or synthetic).
        persist:       If True, saves results to DB (set False in benchmark mode).
        settings:      Optional override — uses get_settings() by default.
    """
    cfg = settings or get_settings()
    llm = get_llm_client(cfg)
    start_ts = time.monotonic()

    policy_agent = PolicyAgent(settings=cfg, llm_client=llm)
    catalog_agent = CatalogAgent(settings=cfg)

    # ── Run agents concurrently ───────────────────────────────────────────────
    # return_exceptions so one agent's hard failure cannot abort the other and
    # lose an otherwise-usable signal.
    policy_raw, catalog_raw = await asyncio.gather(
        policy_agent.evaluate(
            scrape_result.policy_texts,
            blocked=scrape_result.blocked,
            block_reason=scrape_result.block_reason,
        ),
        catalog_agent.evaluate(scrape_result.products),
        return_exceptions=True,
    )

    if isinstance(policy_raw, BaseException):
        logger.error("PolicyAgent raised unexpectedly for %s: %s", url, policy_raw)
        policy_result = PolicyResult(
            is_compliant=False,
            policy_score=0.0,
            missing_disclosures=["Policy analysis failed"],
            agent_error=str(policy_raw),
            evaluated_by="none",
        )
    else:
        policy_result = policy_raw

    if isinstance(catalog_raw, BaseException):
        logger.error("CatalogAgent raised unexpectedly for %s: %s", url, catalog_raw)
        catalog_result = CatalogResult(
            has_prohibited_items=False,
            catalog_score=1.0,
            flagged_items=[],
            checked_via_vectors=False,
            agent_error=str(catalog_raw),
        )
    else:
        catalog_result = catalog_raw

    # ── Scoring ───────────────────────────────────────────────────────────────
    risk_score, guardrail_triggered, guardrail_reason = _compute_risk_score(
        policy_result, catalog_result, domain_info
    )
    risk_tier = _determine_tier(risk_score)

    # An unverifiable merchant is not a safe merchant. When the site blocked
    # inspection we have no compliance evidence either way, so the verdict is
    # floored at MANUAL_REVIEW: not HIGH_RISK (nothing incriminating was found),
    # but never auto-approved on evidence we could not collect.
    if policy_result.inconclusive and risk_tier is RiskTier.SAFE:
        risk_tier = RiskTier.MANUAL_REVIEW

    # ── Audit narrative ───────────────────────────────────────────────────────
    audit_trail, llm_narrative = await _generate_audit_narrative(
        url=url,
        risk_score=risk_score,
        risk_tier=risk_tier,
        domain=domain_info,
        policy=policy_result,
        catalog=catalog_result,
        guardrail_triggered=guardrail_triggered,
        guardrail_reason=guardrail_reason,
        llm=llm,
    )

    degraded_reasons: list[str] = []
    if scrape_result.blocked:
        degraded_reasons.append(
            f"scrape: site blocked automated inspection"
            f"{f' ({scrape_result.block_reason})' if scrape_result.block_reason else ''}"
            " — policy compliance could not be verified"
        )
    if policy_result.evaluated_by != "llm" and policy_result.agent_error and not policy_result.inconclusive:
        degraded_reasons.append(f"policy: {policy_result.agent_error}")
    if not catalog_result.checked_via_vectors:
        degraded_reasons.append(
            f"catalog: {catalog_result.agent_error or 'keyword fallback (patterns not seeded)'}"
        )
    if not llm_narrative:
        degraded_reasons.append("narrative: template (LLM unavailable)")

    # ── Findings payload ──────────────────────────────────────────────────────
    findings = {
        "domain": {
            "domain": domain_info.domain,
            "domain_age_days": domain_info.domain_age_days,
            "is_ssl_valid": domain_info.is_ssl_valid,
            "ssl_expiry_days": domain_info.ssl_expiry_days,
            "registrar": domain_info.registrar,
            "registration_date": domain_info.registration_date,
        },
        "policy": {
            "is_compliant": policy_result.is_compliant,
            "policy_score": round(policy_result.policy_score, 4),
            "missing_disclosures": policy_result.missing_disclosures,
            "evaluated_by": policy_result.evaluated_by,
            "agent_error": policy_result.agent_error,
            "inconclusive": policy_result.inconclusive,
        },
        "catalog": {
            "has_prohibited_items": catalog_result.has_prohibited_items,
            "catalog_score": round(catalog_result.catalog_score, 4),
            "checked_via_vectors": catalog_result.checked_via_vectors,
            "agent_error": catalog_result.agent_error,
            "flagged_items": [
                {
                    "product_title": fi.product_title,
                    "matched_category": fi.matched_category,
                    "matched_pattern": fi.matched_pattern,
                    "similarity_score": round(fi.similarity_score, 4),
                }
                for fi in catalog_result.flagged_items
            ],
        },
        "scoring": {
            "risk_score": round(risk_score, 2),
            "risk_tier": risk_tier.value,
            "guardrail_triggered": guardrail_triggered,
            "guardrail_reason": guardrail_reason,
            "domain_risk_component": round(_compute_domain_risk(domain_info), 2),
            "policy_component": round(
                _POLICY_WEIGHT * (100.0 - policy_result.policy_score * 100.0), 2
            ),
            "catalog_component": round(
                _CATALOG_WEIGHT * (100.0 - catalog_result.catalog_score * 100.0), 2
            ),
            "weights": {
                "policy": _POLICY_WEIGHT,
                "catalog": _CATALOG_WEIGHT,
                "domain": _DOMAIN_WEIGHT,
            },
        },
        "scrape": {
            "title": scrape_result.title,
            "meta_description": scrape_result.meta_description,
            "products_found": len(scrape_result.products),
            "policy_pages_found": sum([
                bool(scrape_result.policy_texts.terms),
                bool(scrape_result.policy_texts.privacy),
                bool(scrape_result.policy_texts.refund),
                bool(scrape_result.policy_texts.contact),
            ]),
            "scrape_error": scrape_result.error,
            "blocked": scrape_result.blocked,
            "block_reason": scrape_result.block_reason,
            "http_status": scrape_result.http_status,
        },
        # Surfaced so the UI can say "this verdict ran in degraded mode"
        # instead of presenting a fallback score as a full analysis.
        "analysis_quality": {
            "fully_analyzed": not degraded_reasons,
            "llm_narrative": llm_narrative,
            "degraded_reasons": degraded_reasons,
        },
    }

    elapsed_ms = int((time.monotonic() - start_ts) * 1000)

    # ── Persist to DB ─────────────────────────────────────────────────────────
    merchant_id = "benchmark-synthetic"
    scan_id = str(uuid.uuid4())

    if persist:
        try:
            merchant_id, scan_id = await _persist_scan(
                url=url,
                risk_score=risk_score,
                risk_tier=risk_tier,
                findings=findings,
                audit_trail=audit_trail,
            )
        except Exception as exc:  # noqa: BLE001 — a DB outage must not void the verdict
            logger.error("DB persistence failed for %s: %s", url, exc)
            findings["analysis_quality"]["degraded_reasons"].append(
                f"persistence: {exc}"
            )
            findings["analysis_quality"]["fully_analyzed"] = False
            scan_id = str(uuid.uuid4())

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return ScanReport(
        scan_id=scan_id,
        merchant_id=merchant_id,
        domain=domain_info.domain,
        risk_score=round(risk_score, 2),
        risk_tier=risk_tier.value,
        domain_info=findings["domain"],
        policy_result=findings["policy"],
        catalog_result=findings["catalog"],
        findings=findings,
        audit_trail=audit_trail,
        guardrail_triggered=guardrail_triggered,
        guardrail_reason=guardrail_reason,
        processing_time_ms=elapsed_ms,
        created_at=now_iso,
        llm_narrative=llm_narrative,
        fully_analyzed=bool(findings["analysis_quality"]["fully_analyzed"]),
    )


# ─── Live API entry point ─────────────────────────────────────────────────────

async def run_full_inspection(url: str) -> ScanReport:
    """
    Full end-to-end merchant inspection:
      1. Scrape homepage + policy pages (Playwright)
      2. Inspect domain (WHOIS + SSL)
      3. Run policy + catalog agents concurrently
      4. Apply guardrails → compute score → generate narrative
      5. Persist to Neon DB

    This is the function called by POST /api/v1/inspect.
    """
    logger.info("Starting full inspection for: %s", url)
    settings = get_settings()

    # Scraping and domain inspection run concurrently. Both are written to
    # return a value rather than raise, but return_exceptions guards against a
    # surprise so one dead subsystem cannot take down the whole inspection.
    scrape_result, domain_info = await asyncio.gather(
        scrape_merchant(url, max_products=settings.max_products_per_scan),
        inspect_domain(url),
        return_exceptions=True,
    )

    if isinstance(scrape_result, BaseException):
        logger.error("Scrape failed hard for %s: %s", url, scrape_result)
        from razorshield_backend.scrapers.browser import PolicyTexts

        scrape_result = MerchantScrapeResult(
            url=url,
            title="",
            meta_description="",
            homepage_text="",
            policy_texts=PolicyTexts(),
            error=str(scrape_result),
        )

    if isinstance(domain_info, BaseException):
        logger.error("Domain inspection failed hard for %s: %s", url, domain_info)
        from razorshield_backend.scrapers.whois_client import _get_root_domain

        domain_info = DomainInspection(
            domain=_get_root_domain(url),
            domain_age_days=-1,
            is_ssl_valid=False,
            ssl_expiry_days=-1,
            registrar="",
            registration_date=None,
        )

    return await score_from_raw_data(
        url=url,
        scrape_result=scrape_result,
        domain_info=domain_info,
        persist=True,
        settings=settings,
    )
