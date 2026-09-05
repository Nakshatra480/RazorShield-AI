"""
razorshield_backend/benchmark.py
──────────────────────────────────
Synthetic evaluation harness for RazorShield AI.

Workflow:
  1. Seed the `prohibited_patterns` table with 30 categories of forbidden items
     (each encoded using the local BAAI/bge-base-en-v1.5 model).
  2. Generate 50 synthetic merchant profiles:
       35 "SAFE" merchants  — established domains, compliant policies, clean catalog
       15 "HIGH_RISK" merchants — new domains / bad policies / prohibited items
  3. Run score_from_raw_data() across all 50 with asyncio.Semaphore(5) to
     respect OpenRouter rate limits while still parallelising evaluations.
  4. Compute confusion matrix, precision, recall, F1 and false-positive cost.
  5. Write results to `public/benchmark_results.json` for the Next.js frontend.

Usage:
  cd RazorShield-AI
  python -m razorshield_backend.benchmark
  (or triggered via POST /api/v1/benchmark/run)
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sqlalchemy import text

from razorshield_backend.agents.catalog_agent import _load_embedding_model, _EMBED_LOCK
from razorshield_backend.agents.orchestrator import get_llm_client, score_from_raw_data
from razorshield_backend.config import get_settings
from razorshield_backend.db.database import get_session, init_db
from razorshield_backend.db.models import ProhibitedPattern
from razorshield_backend.scrapers.browser import (
    MerchantScrapeResult,
    PolicyTexts,
    ProductItem,
)
from razorshield_backend.scrapers.whois_client import DomainInspection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

RESULTS_PATH = Path(__file__).parent.parent / "public" / "benchmark_results.json"

# Fixed seed so the reported precision/recall describe a reproducible dataset.
# Without it every run generated a different set of synthetic merchants, so two
# runs of "the same" benchmark were not comparable and a regression could not be
# distinguished from resampling noise. Override with RAZORSHIELD_BENCHMARK_SEED.
BENCHMARK_SEED = int(os.getenv("RAZORSHIELD_BENCHMARK_SEED", "20240915"))

# Cost model inputs. Named constants rather than magic numbers so the dashboard
# can display the assumptions behind the projected figures.
COST_PER_FALSE_POSITIVE_USD = 150      # lost merchant lifetime value
COST_PER_FALSE_NEGATIVE_USD = 2500     # chargebacks + scheme fines for onboarding a fraudster
MONTHLY_MERCHANT_VOLUME = 1000         # onboarding volume the projection assumes

# ─── Prohibited item seed catalogue ──────────────────────────────────────────

PROHIBITED_CATALOGUE: list[dict] = [
    # Weapons
    {"category": "firearms", "text": "illegal firearms and handguns for sale without license"},
    {"category": "firearms", "text": "unlicensed semi-automatic rifles and assault weapons"},
    {"category": "ammunition", "text": "bulk ammunition, hollow-point bullets, incendiary rounds"},
    {"category": "weapons", "text": "switchblade knives, brass knuckles, illegal melee weapons"},
    {"category": "weapons", "text": "ghost guns unregistered untraceable firearm parts kits"},
    # Drugs
    {"category": "narcotics", "text": "fentanyl pills opioid powder illegal drug sale online"},
    {"category": "narcotics", "text": "methamphetamine crystal meth stimulant drug purchase"},
    {"category": "narcotics", "text": "cocaine powder heroin black tar street drug buy"},
    {"category": "pharmaceuticals", "text": "prescription opioids without prescription oxycodone hydrocodone"},
    {"category": "research_chemicals", "text": "designer research chemicals synthetic cannabinoids bath salts"},
    # Counterfeit
    {"category": "counterfeit_goods", "text": "fake Rolex replica luxury watch counterfeit designer goods"},
    {"category": "counterfeit_goods", "text": "knockoff Louis Vuitton Gucci Chanel counterfeit handbag"},
    {"category": "counterfeit_currency", "text": "fake money counterfeit bills prop currency forged banknote"},
    # Digital fraud
    {"category": "stolen_credentials", "text": "hacked accounts stolen credentials Netflix Spotify login"},
    {"category": "stolen_data", "text": "database dump credit card numbers CVV stolen identity"},
    {"category": "malware", "text": "ransomware keylogger RAT malware trojan exploit kit sale"},
    {"category": "fraud_tools", "text": "carding tools fraud kit phishing pages scam infrastructure"},
    # Exploitation
    {"category": "gambling", "text": "offshore casino gambling chips bet credits unlicensed poker"},
    {"category": "pyramid_scheme", "text": "MLM pyramid scheme get rich quick investment fraud scheme"},
    {"category": "trafficking", "text": "human trafficking smuggling undocumented workers exploitation"},
    # Unregulated financial
    {"category": "unregistered_securities", "text": "unregistered securities investment tokens unlicensed ICO"},
    {"category": "money_laundering", "text": "money laundering shell company offshore accounts illicit funds"},
    # Tobacco / age-restricted
    {"category": "tobacco_underage", "text": "cigarettes tobacco products sold to minors no age check"},
    {"category": "alcohol_underage", "text": "alcohol spirits shipped without age verification"},
    # Cybercrime services
    {"category": "ddos_services", "text": "DDoS booter stresser service attack infrastructure for hire"},
    {"category": "spam_services", "text": "spam email lists bulk unsolicited email marketing bot"},
    # Exotic animals
    {"category": "wildlife_trafficking", "text": "endangered species ivory rhino horn exotic animal parts"},
    # Sanctions
    {"category": "sanctions_evasion", "text": "sanctioned country goods OFAC SDN evasion bypass"},
    # Nuclear / CBRN
    {"category": "hazmat", "text": "radioactive materials chemical biological precursors hazmat"},
    # Piracy
    {"category": "piracy", "text": "pirated software cracked games warez license key generator"},
]


# ─── Synthetic merchant profile generators ────────────────────────────────────

def _make_policy_texts(compliant: bool) -> PolicyTexts:
    """Generate realistic policy texts for compliant vs non-compliant merchants."""
    if compliant:
        return PolicyTexts(
            terms=(
                "These Terms of Service govern your use of ShopCo Ltd (UK registered company no. 12345678). "
                "Users must be 18 years or older. Prohibited uses include fraud, spam, and illegal activities. "
                "Last updated 2024-01-15."
            ),
            privacy=(
                "ShopCo Ltd collects your name, email, and payment information to process orders. "
                "Data is stored encrypted on AWS servers in the EU. We do not sell data to third parties. "
                "You may request deletion by emailing privacy@shopco.example.com."
            ),
            refund=(
                "You may return unused items within 30 days of purchase for a full refund. "
                "Contact support@shopco.example.com to initiate a return. "
                "Refunds are processed within 5–7 business days."
            ),
            contact=(
                "Contact us at support@shopco.example.com or +44 20 1234 5678. "
                "Business hours: Mon–Fri 9am–6pm GMT."
            ),
        )
    else:
        # Incomplete / missing policies
        choice = random.randint(0, 3)
        if choice == 0:
            return PolicyTexts()  # no policies at all
        elif choice == 1:
            return PolicyTexts(
                terms="By using this site you agree to our terms.",  # vague
            )
        elif choice == 2:
            return PolicyTexts(
                privacy="We may share your data with partners.",  # no specifics
                terms="Terms apply. Contact us for details.",
            )
        else:
            return PolicyTexts(
                refund="All sales are final. No refunds.",
            )


def _make_products(risky: bool, prohibited_patterns: Optional[list[dict]] = None) -> list[ProductItem]:
    """Generate product listings for safe vs high-risk merchants."""
    if not risky:
        safe_products = [
            ProductItem("Organic Cotton T-Shirt", "100% organic fair-trade cotton, machine washable", "$29.99"),
            ProductItem("Bamboo Cutting Board", "Eco-friendly bamboo kitchen cutting board, 18x12 inch", "$34.99"),
            ProductItem("Stainless Steel Water Bottle", "32 oz BPA-free insulated bottle, keeps cold 24h", "$24.99"),
            ProductItem("Wireless Charging Pad", "10W fast wireless charger compatible with Qi devices", "$19.99"),
            ProductItem("Reusable Grocery Bags", "Set of 5 heavy-duty woven shopping bags, 50lb capacity", "$14.99"),
        ]
        return random.sample(safe_products, min(3, len(safe_products)))

    # Choose 1–2 prohibited items from the catalogue
    if prohibited_patterns:
        choices = random.sample(prohibited_patterns, min(2, len(prohibited_patterns)))
        items = [ProductItem(c["text"][:60], c["text"], "$99.99") for c in choices]
    else:
        # Fallback prohibited products
        items = [
            ProductItem("Bulk Hollow Point Ammunition", "500 rounds .45 ACP jacketed hollow points", "$189.99"),
            ProductItem("Prescription Oxycodone 80mg", "High strength pain relief no prescription needed", "$299.99"),
        ]
    return items


def _make_domain_info(risky: bool, idx: int) -> DomainInspection:
    """Generate synthetic domain inspection data."""
    if risky:
        age_days = random.choice([0, 1, 2, 3, 5, 8, 15, 20])
        ssl_valid = random.choice([True, False, False])  # often no SSL
    else:
        age_days = random.randint(365, 3650)  # 1–10 years
        ssl_valid = True

    return DomainInspection(
        domain=f"merchant-{idx:03d}-{'bad' if risky else 'ok'}.example.com",
        domain_age_days=age_days,
        is_ssl_valid=ssl_valid,
        ssl_expiry_days=random.randint(30, 360) if ssl_valid else -1,
        registrar="GoDaddy" if not risky else random.choice(["NameCheap", "Epik Inc", "Unknown"]),
        registration_date=None,
    )


def _make_scrape_result(
    url: str,
    risky: bool,
    idx: int,
    prohibited_patterns: Optional[list[dict]] = None,
) -> MerchantScrapeResult:
    """Build a complete synthetic MerchantScrapeResult."""
    return MerchantScrapeResult(
        url=url,
        title=(
            "BestDeals Online Store" if not risky
            else random.choice(["QuickBuy24", "FastShip Store", "DarkMart Pro"])
        ),
        meta_description=(
            "Quality products for everyday life — free shipping on orders over $50."
            if not risky
            else "Discreet shipping. No questions asked. Fast delivery worldwide."
        ),
        homepage_text=(
            "Welcome to our store. We offer a wide range of organic and eco-friendly products. "
            "All items are ethically sourced. Free returns within 30 days."
            if not risky
            else "Best prices on exclusive items. Worldwide discreet shipping. "
                 "No verification required. Trusted by thousands of customers."
        ),
        policy_texts=_make_policy_texts(compliant=not risky),
        products=_make_products(risky=risky, prohibited_patterns=prohibited_patterns),
    )


# ─── Prohibited pattern seeder ────────────────────────────────────────────────

async def seed_prohibited_patterns() -> int:
    """
    Embed all prohibited catalogue entries and upsert them into the DB.
    Returns number of patterns seeded.
    """
    settings = get_settings()
    model: SentenceTransformer = _load_embedding_model(settings.embedding_model_name)

    texts = [item["text"] for item in PROHIBITED_CATALOGUE]
    logger.info("Embedding %d prohibited patterns...", len(texts))
    with _EMBED_LOCK:
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=16,
        )

    async with get_session() as session:
        # Clear existing patterns to avoid duplicates on re-run
        await session.execute(text("DELETE FROM prohibited_patterns"))
        await session.flush()

        for item, emb in zip(PROHIBITED_CATALOGUE, embeddings):
            pattern = ProhibitedPattern(
                category=item["category"],
                pattern_text=item["text"],
                embedding=emb.tolist(),
            )
            session.add(pattern)

        await session.flush()

    logger.info("Seeded %d prohibited patterns into pgvector table.", len(PROHIBITED_CATALOGUE))
    return len(PROHIBITED_CATALOGUE)


# ─── Benchmark runner ─────────────────────────────────────────────────────────

async def run_benchmark() -> dict:
    """
    Execute full benchmark evaluation over 50 synthetic merchants.

    Returns metrics dict that is also written to public/benchmark_results.json.
    """
    settings = get_settings()
    logger.info("=== RazorShield AI Benchmark Starting (seed=%d) ===", BENCHMARK_SEED)

    # Reset the RNG so the 50 synthetic profiles are identical run to run.
    random.seed(BENCHMARK_SEED)

    # 1. Init DB + seed prohibited patterns
    await init_db()
    await seed_prohibited_patterns()

    # 2. Build synthetic merchant profiles
    # True label: 0 = SAFE, 1 = HIGH_RISK
    profiles: list[tuple[str, MerchantScrapeResult, DomainInspection, int]] = []

    for i in range(35):
        url = f"https://merchant-{i:03d}-safe.example.com"
        scrape = _make_scrape_result(url, risky=False, idx=i)
        domain = _make_domain_info(risky=False, idx=i)
        profiles.append((url, scrape, domain, 0))

    for i in range(15):
        url = f"https://merchant-{i:03d}-risk.example.com"
        scrape = _make_scrape_result(
            url, risky=True, idx=i + 35, prohibited_patterns=PROHIBITED_CATALOGUE
        )
        domain = _make_domain_info(risky=True, idx=i + 35)
        profiles.append((url, scrape, domain, 1))

    # Shuffle to randomise processing order
    random.shuffle(profiles)

    # 3. Run scoring concurrently, bounded by the configured concurrency limit
    # (previously hardcoded to 3 while logging settings.max_concurrent_inspections,
    # so the number reported in the logs was not the number actually used).
    semaphore = asyncio.Semaphore(settings.max_concurrent_inspections)
    y_true: list[int] = []
    y_pred: list[int] = []
    scan_details: list[dict] = []

    async def evaluate_one(
        url: str,
        scrape: MerchantScrapeResult,
        domain: DomainInspection,
        true_label: int,
    ) -> None:
        async with semaphore:
            try:
                report = await score_from_raw_data(
                    url=url,
                    scrape_result=scrape,
                    domain_info=domain,
                    persist=False,          # don't write synthetic data to prod DB
                    settings=settings,
                )
                pred_label = 1 if report.risk_tier == "HIGH_RISK" else 0
                y_true.append(true_label)
                y_pred.append(pred_label)
                scan_details.append({
                    "url": url,
                    "true_label": "HIGH_RISK" if true_label else "SAFE",
                    "predicted": report.risk_tier,
                    "risk_score": report.risk_score,
                    "correct": pred_label == true_label,
                    "guardrail": report.guardrail_triggered,
                    "processing_ms": report.processing_time_ms,
                    "fully_analyzed": report.fully_analyzed,
                })
            except Exception as exc:
                logger.error("Benchmark evaluation failed for %s: %s", url, exc)
                # Count as incorrect prediction
                y_true.append(true_label)
                y_pred.append(1 - true_label)

    tasks = [evaluate_one(url, scrape, domain, label) for url, scrape, domain, label in profiles]
    logger.info(
        "Running %d evaluations (concurrency=%d)...",
        len(tasks),
        settings.max_concurrent_inspections,
    )
    await asyncio.gather(*tasks)

    # 4. Compute metrics
    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)

    cm = confusion_matrix(y_true_arr, y_pred_arr, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()

    precision = float(precision_score(y_true_arr, y_pred_arr, zero_division=0))
    recall = float(recall_score(y_true_arr, y_pred_arr, zero_division=0))
    f1 = float(f1_score(y_true_arr, y_pred_arr, zero_division=0))

    # False-positive cost: FP × $150 (lost merchant LTV) + FN × $2,500 (chargeback fine)
    false_positive_cost = int(fp * COST_PER_FALSE_POSITIVE_USD + fn * COST_PER_FALSE_NEGATIVE_USD)
    accuracy = float(np.mean(y_true_arr == y_pred_arr))

    avg_processing_ms = (
        int(np.mean([d["processing_ms"] for d in scan_details]))
        if scan_details else 0
    )

    # ── Cost model ────────────────────────────────────────────────────────────
    # Projected from THIS run's measured error rates. Every input is stated in
    # the output so the dashboard can show the assumptions alongside the number.
    #
    # The previous version emitted six months of "chart_data" generated by
    # multiplying one measurement by a hardcoded `1.0 - month * 0.05` ramp, and
    # the UI plotted it as a time series. That is a fabricated trend: the
    # benchmark runs once and has no historical data. It has been replaced with
    # the single-run cost breakdown that the numbers actually support.
    fp_rate = fp / max(tn + fp, 1)          # share of safe merchants wrongly blocked
    fn_rate = fn / max(tp + fn, 1)          # share of risky merchants wrongly approved
    prevalence = (tp + fn) / max(len(y_true), 1)

    monthly_fp_cost = int(fp_rate * MONTHLY_MERCHANT_VOLUME * COST_PER_FALSE_POSITIVE_USD)
    monthly_fn_cost = int(fn_rate * MONTHLY_MERCHANT_VOLUME * prevalence * COST_PER_FALSE_NEGATIVE_USD)
    # Fraud caught = risky merchants correctly blocked, at the same unit cost
    # that an escaped one would have incurred.
    monthly_fraud_prevented = int(
        (1 - fn_rate) * MONTHLY_MERCHANT_VOLUME * prevalence * COST_PER_FALSE_NEGATIVE_USD
    )

    llm_health = get_llm_client(settings).health
    degraded_count = sum(1 for d in scan_details if not d.get("fully_analyzed", True))

    results = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Provenance: the dashboard reads these instead of hardcoding a model
        # name, which previously showed "GPT-4o / LangGraph" for a run that
        # actually used Llama 3.1 through LiteLLM.
        "config": {
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model_name,
            "similarity_threshold": settings.prohibited_similarity_threshold,
            "concurrency": settings.max_concurrent_inspections,
            "random_seed": BENCHMARK_SEED,
            "llm_available": bool(llm_health.available) if llm_health else None,
            "llm_detail": llm_health.detail if llm_health else None,
            "degraded_evaluations": degraded_count,
        },
        "dataset": {
            "total_merchants": len(profiles),
            "safe_merchants": 35,
            "high_risk_merchants": 15,
        },
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "accuracy": round(accuracy, 4),
            "avg_processing_ms": avg_processing_ms,
        },
        "confusion_matrix": {
            "true_positive": int(tp),
            "false_positive": int(fp),
            "true_negative": int(tn),
            "false_negative": int(fn),
        },
        "financial_impact": {
            "false_positive_cost_per_merchant_usd": COST_PER_FALSE_POSITIVE_USD,
            "false_negative_cost_per_merchant_usd": COST_PER_FALSE_NEGATIVE_USD,
            "total_benchmark_cost_usd": false_positive_cost,
            "monthly_fraud_prevented_usd": monthly_fraud_prevented,
            "monthly_false_decline_cost_usd": monthly_fp_cost,
            "monthly_missed_fraud_cost_usd": monthly_fn_cost,
        },
        # Single-run projection with its inputs attached, so the dashboard can
        # show "modelled at N merchants/month" rather than implying measurement.
        "cost_model": {
            "basis": "single benchmark run; projected linearly to monthly volume",
            "monthly_merchant_volume": MONTHLY_MERCHANT_VOLUME,
            "high_risk_prevalence": round(prevalence, 4),
            "false_positive_rate": round(fp_rate, 4),
            "false_negative_rate": round(fn_rate, 4),
            "cost_per_false_positive_usd": COST_PER_FALSE_POSITIVE_USD,
            "cost_per_false_negative_usd": COST_PER_FALSE_NEGATIVE_USD,
            "monthly_false_decline_cost_usd": monthly_fp_cost,
            "monthly_missed_fraud_cost_usd": monthly_fn_cost,
            "monthly_fraud_prevented_usd": monthly_fraud_prevented,
        },
        "scan_details": scan_details,
    }

    # 5. Write to public/ for Next.js frontend
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = RESULTS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    os.replace(tmp_path, RESULTS_PATH)  # atomic — readers never see a partial file

    logger.info("=== Benchmark Complete ===")
    logger.info("Precision: %.4f | Recall: %.4f | F1: %.4f | Accuracy: %.4f",
                precision, recall, f1, accuracy)
    logger.info("Confusion Matrix — TP:%d FP:%d TN:%d FN:%d", tp, fp, tn, fn)
    logger.info("Total false-positive cost: $%s", f"{false_positive_cost:,}")
    if degraded_count:
        logger.warning(
            "%d/%d evaluations ran in degraded mode (LLM or pgvector unavailable) — "
            "metrics reflect fallback scoring.",
            degraded_count,
            len(scan_details),
        )
    logger.info("Results written to: %s", RESULTS_PATH)

    return results


# ─── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run_benchmark())
