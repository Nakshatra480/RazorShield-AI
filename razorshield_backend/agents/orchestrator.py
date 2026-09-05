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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import litellm

from razorshield_backend.agents.catalog_agent import CatalogAgent, CatalogResult
from razorshield_backend.agents.policy_agent import PolicyAgent, PolicyResult
from razorshield_backend.config import Settings, get_settings
from razorshield_backend.db.database import get_session
from razorshield_backend.db.models import Merchant, RiskTier, Scan
from razorshield_backend.scrapers.browser import (
    MerchantScrapeResult,
    PolicyTexts,
    ProductItem,
    scrape_merchant,
)
from razorshield_backend.scrapers.whois_client import DomainInspection, inspect_domain

logger = logging.getLogger(__name__)
litellm.drop_params = True


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
    if domain.domain_age_days >= 0 and domain.domain_age_days < 3 and policy.policy_score < 0.4:
        return 95.0, True, (
            f"Domain registered {domain.domain_age_days} day(s) ago with "
            f"policy compliance score {policy.policy_score:.2f} — automatic HIGH_RISK."
        )

    # ── Guardrail B: prohibited goods detected ────────────────────────────────
    if catalog.has_prohibited_items:
        categories = list({item.matched_category for item in catalog.flagged_items})
        return 90.0, True, (
            f"Prohibited items detected in merchant catalogue: "
            f"{', '.join(categories[:3])}."
        )

    # ── Weighted composite ────────────────────────────────────────────────────
    domain_risk = _compute_domain_risk(domain)
    policy_component = 0.4 * (100.0 - policy.policy_score * 100.0)
    catalog_component = 0.4 * (100.0 - catalog.catalog_score * 100.0)
    domain_component = 0.2 * domain_risk

    risk_score = policy_component + catalog_component + domain_component
    risk_score = max(0.0, min(100.0, risk_score))

    return risk_score, False, None


# ─── Audit narrative generator ────────────────────────────────────────────────

_AUDIT_SYSTEM_PROMPT = """You are a senior risk analyst at a payment gateway writing a formal inspection report.
Write a concise (200–300 word) plain-text audit narrative explaining the risk verdict for this merchant.
Cover: what was found during policy review, catalog check, and domain inspection.
State the risk tier and why. Do NOT use bullet points or markdown — write formal prose paragraphs."""


async def _generate_audit_narrative(
    url: str,
    risk_score: float,
    risk_tier: RiskTier,
    domain: DomainInspection,
    policy: PolicyResult,
    catalog: CatalogResult,
    guardrail_triggered: bool,
    guardrail_reason: Optional[str],
    settings: Settings,
) -> str:
    """Generate a human-readable audit narrative via LLM. Falls back to template on error."""

    flagged_str = (
        ", ".join(item.product_title for item in catalog.flagged_items[:3])
        if catalog.flagged_items else "none"
    )
    missing_str = (
        "; ".join(policy.missing_disclosures[:4])
        if policy.missing_disclosures else "none"
    )

    context = (
        f"Merchant URL: {url}\n"
        f"Domain: {domain.domain} | Age: {domain.domain_age_days} days | "
        f"SSL valid: {domain.is_ssl_valid} | Registrar: {domain.registrar}\n"
        f"Policy compliance score: {policy.policy_score:.2f} | "
        f"Missing disclosures: {missing_str}\n"
        f"Catalog safety score: {catalog.catalog_score:.2f} | "
        f"Flagged items: {flagged_str}\n"
        f"Final risk score: {risk_score:.1f}/100 | Risk tier: {risk_tier.value}\n"
        f"Guardrail triggered: {guardrail_triggered}"
        + (f" — {guardrail_reason}" if guardrail_reason else "")
    )

    try:
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.2,
            max_tokens=512,
            api_base=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
        return response.choices[0].message.content.strip()

    except Exception as exc:
        logger.warning("Audit narrative generation failed: %s — using template.", exc)
        return (
            f"Merchant domain {domain.domain} was inspected on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
            f"Domain age: {domain.domain_age_days} days. SSL valid: {domain.is_ssl_valid}. "
            f"Policy compliance score: {policy.policy_score:.2f} with missing disclosures: {missing_str}. "
            f"Catalog safety score: {catalog.catalog_score:.2f}; flagged items: {flagged_str}. "
            f"{'Guardrail override applied: ' + (guardrail_reason or '') + ' ' if guardrail_triggered else ''}"
            f"Final verdict: {risk_tier.value} (score {risk_score:.1f}/100)."
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
    async with get_session() as session:
        # Upsert merchant (idempotent on domain_url)
        from sqlalchemy import select
        stmt = select(Merchant).where(Merchant.domain_url == url)
        result = await session.execute(stmt)
        merchant = result.scalar_one_or_none()

        if merchant is None:
            merchant = Merchant(domain_url=url)
            session.add(merchant)
            await session.flush()   # assigns UUID before referencing in Scan

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
    start_ts = time.monotonic()

    policy_agent = PolicyAgent(settings=cfg)
    catalog_agent = CatalogAgent(settings=cfg)

    # ── Run agents concurrently ───────────────────────────────────────────────
    policy_result, catalog_result = await asyncio.gather(
        policy_agent.evaluate(scrape_result.policy_texts),
        catalog_agent.evaluate(scrape_result.products),
    )

    # ── Scoring ───────────────────────────────────────────────────────────────
    risk_score, guardrail_triggered, guardrail_reason = _compute_risk_score(
        policy_result, catalog_result, domain_info
    )
    risk_tier = _determine_tier(risk_score)

    # ── Audit narrative ───────────────────────────────────────────────────────
    audit_trail = await _generate_audit_narrative(
        url=url,
        risk_score=risk_score,
        risk_tier=risk_tier,
        domain=domain_info,
        policy=policy_result,
        catalog=catalog_result,
        guardrail_triggered=guardrail_triggered,
        guardrail_reason=guardrail_reason,
        settings=cfg,
    )

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
        },
        "catalog": {
            "has_prohibited_items": catalog_result.has_prohibited_items,
            "catalog_score": round(catalog_result.catalog_score, 4),
            "checked_via_vectors": catalog_result.checked_via_vectors,
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
            "policy_component": round(0.4 * (100.0 - policy_result.policy_score * 100.0), 2),
            "catalog_component": round(0.4 * (100.0 - catalog_result.catalog_score * 100.0), 2),
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
        except Exception as exc:
            logger.error("DB persistence failed for %s: %s", url, exc)
            # Non-fatal — return result without DB record
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

    # Scraping and domain inspection can run concurrently
    scrape_result, domain_info = await asyncio.gather(
        scrape_merchant(url),
        inspect_domain(url),
        return_exceptions=False,
    )

    return await score_from_raw_data(
        url=url,
        scrape_result=scrape_result,
        domain_info=domain_info,
        persist=True,
        settings=settings,
    )
