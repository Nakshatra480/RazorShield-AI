"""
tests/test_agents.py
─────────────────────────────────────────────────────────────────────────────
Multi-agent engine tests: PolicyAgent, CatalogAgent, and Orchestrator.

Tests that need live infrastructure declare it (`llm_available`, `require_db`)
and skip when it is genuinely absent, so an expired API key surfaces as a skip
rather than a misleading failure. The deterministic logic — the heuristic policy
scorer, error classification, guardrails, and the weighted score — is covered
with no external I/O at all.
"""

import pytest

from razorshield_backend.agents.policy_agent import (
    PolicyResult,
    evaluate_policy_heuristic,
)
from razorshield_backend.scrapers.browser import PolicyTexts


# ── Heuristic policy scorer (no I/O) ──────────────────────────────────────────

def test_heuristic_scores_fully_compliant_policy_highly(safe_scrape_result):
    """
    A policy set containing all five rubric items must score high.

    This is the regression guard for the core bug in the previous build: when
    the LLM was unavailable the agent returned 0.0 for *every* merchant, so a
    fully compliant one was scored identically to a merchant with no policies
    at all — while policy still carried 40% of the risk weight.
    """
    result = evaluate_policy_heuristic(safe_scrape_result.policy_texts)

    print(f"\n  policy_score={result.policy_score}")
    print(f"  missing={result.missing_disclosures}")

    assert result.evaluated_by == "heuristic"
    assert result.policy_score >= 0.8, (
        f"Compliant policy scored {result.policy_score}; expected >= 0.8.\n"
        f"missing={result.missing_disclosures}"
    )
    assert result.is_compliant is True
    print("  [PASS] Heuristic scorer credits a fully compliant policy set.")


def test_heuristic_scores_empty_policy_zero():
    """No policy text at all is a genuine zero."""
    result = evaluate_policy_heuristic(PolicyTexts())
    assert result.policy_score == 0.0
    assert result.is_compliant is False
    assert result.missing_disclosures == ["No policy pages accessible"]
    print("\n  [PASS] Empty policy scored 0.0.")


def test_heuristic_scores_vague_policy_low():
    """A one-line hand-wave must not pass as compliant."""
    result = evaluate_policy_heuristic(
        PolicyTexts(terms="By using this site you agree to our terms.")
    )
    print(f"\n  policy_score={result.policy_score} missing={len(result.missing_disclosures)}")
    assert result.policy_score <= 0.4, f"Vague policy scored too high: {result.policy_score}"
    assert result.is_compliant is False
    print("  [PASS] Vague policy correctly scored low.")


def test_heuristic_is_deterministic(safe_scrape_result):
    """Identical input must always produce an identical verdict."""
    a = evaluate_policy_heuristic(safe_scrape_result.policy_texts)
    b = evaluate_policy_heuristic(safe_scrape_result.policy_texts)
    assert (a.policy_score, a.is_compliant, a.missing_disclosures) == (
        b.policy_score, b.is_compliant, b.missing_disclosures
    )
    print("\n  [PASS] Heuristic scorer is deterministic.")


@pytest.mark.parametrize(
    "texts,should_find_contact",
    [
        (PolicyTexts(contact="Email: help@shop.example.com"), True),
        (PolicyTexts(contact="Phone: +44 20 1234 5678"), True),
        # A price and an ISO date must not be mistaken for a phone number.
        (PolicyTexts(contact="Order 1,299 placed on 2024-01-15"), False),
    ],
)
def test_heuristic_contact_detection(texts, should_find_contact):
    """Contact detection must not fire on prices or dates."""
    result = evaluate_policy_heuristic(texts)
    found = "No contact email or phone number found" not in result.missing_disclosures
    assert found is should_find_contact, (
        f"contact detection returned {found} for {texts!r}, expected {should_find_contact}"
    )


# ── LLM error classification (no I/O) ─────────────────────────────────────────

@pytest.mark.parametrize(
    "message,expect_retryable",
    [
        # The exact provider payload this deployment hit — must NOT be retried.
        ('OpenrouterException - {"error":{"message":"Insufficient credits.","code":402}}', False),
        ('{"error":{"message":"Invalid API key","code":401}}', False),
        ('{"error":{"message":"Model not a valid model","code":404}}', False),
        ('{"error":{"message":"Rate limit exceeded","code":429}}', True),
        ('{"error":{"message":"Bad gateway","code":502}}', True),
        ("Connection reset by peer", True),
    ],
)
def test_llm_error_classification(message, expect_retryable):
    """
    Fatal provider errors must be classified as non-retryable.

    The previous agent retried every failure 3× with exponential back-off, so a
    402 "insufficient credits" cost ~6s and 6 doomed HTTP requests per merchant.
    """
    from razorshield_backend.agents.llm import classify_error

    verdict = classify_error(RuntimeError(message))
    assert verdict.retryable is expect_retryable, (
        f"{message[:60]!r} classified retryable={verdict.retryable}, "
        f"expected {expect_retryable}"
    )


def test_llm_timeout_is_retryable():
    import asyncio

    from razorshield_backend.agents.llm import classify_error

    assert classify_error(asyncio.TimeoutError()).retryable is True


@pytest.mark.asyncio
async def test_llm_breaker_stops_repeat_calls_after_fatal_error():
    """
    After every configured credential is exhausted, the breaker must
    short-circuit subsequent calls instead of re-issuing doomed requests for
    each remaining merchant.

    The first call legitimately tries each key once — that is failover, not
    waste. Everything after it must cost zero provider traffic.
    """
    import razorshield_backend.agents.llm as llm_module
    from razorshield_backend.agents.llm import LLMClient, LLMUnavailable
    from razorshield_backend.config import get_settings

    settings = get_settings()
    key_count = len(settings.openrouter_api_keys)
    client = LLMClient(settings)
    calls = {"n": 0}

    async def _fake_acompletion(**_kwargs):
        calls["n"] += 1
        raise RuntimeError('{"error":{"message":"Insufficient credits.","code":402}}')

    original = llm_module.litellm.acompletion
    llm_module.litellm.acompletion = _fake_acompletion
    try:
        with pytest.raises(LLMUnavailable):
            await client.complete(system_prompt="s", user_message="u")
        after_first = calls["n"]

        for _ in range(3):
            with pytest.raises(LLMUnavailable):
                await client.complete(system_prompt="s", user_message="u")
    finally:
        llm_module.litellm.acompletion = original

    assert after_first == key_count, (
        f"First call made {after_first} provider requests for {key_count} configured "
        "key(s); it should try each exactly once."
    )
    assert calls["n"] == after_first, (
        f"The breaker let {calls['n'] - after_first} extra request(s) through after "
        "every key was exhausted."
    )
    print(
        f"\n  [PASS] {key_count} key(s) tried once, then 3 further calls "
        f"short-circuited with 0 provider traffic."
    )


# ── Policy Agent (live LLM, falls back cleanly) ────────────────────────────────

@pytest.mark.asyncio
async def test_policy_agent_returns_valid_result(safe_scrape_result, llm_available):
    """
    PolicyAgent must always return a well-formed PolicyResult, whether the
    verdict came from the LLM or the heuristic fallback.
    """
    from razorshield_backend.agents.orchestrator import get_llm_client
    from razorshield_backend.agents.policy_agent import PolicyAgent
    from razorshield_backend.config import get_settings

    settings = get_settings()
    agent = PolicyAgent(settings=settings, llm_client=get_llm_client(settings))
    result = await agent.evaluate(safe_scrape_result.policy_texts)

    print(f"\n  evaluated_by={result.evaluated_by}")
    print(f"  is_compliant={result.is_compliant}")
    print(f"  policy_score={result.policy_score:.4f}")
    print(f"  missing_disclosures={result.missing_disclosures}")

    assert isinstance(result, PolicyResult)
    assert isinstance(result.is_compliant, bool)
    assert isinstance(result.policy_score, float)
    assert 0.0 <= result.policy_score <= 1.0, f"score out of range: {result.policy_score}"
    assert isinstance(result.missing_disclosures, list)
    assert result.evaluated_by in ("llm", "heuristic", "none")

    if llm_available:
        # The provider can answer the probe and then rate-limit (429) moments
        # later — free tiers do this constantly. Either path is correct; what
        # matters is that a fallback is *reported*, never silently substituted.
        assert result.evaluated_by in ("llm", "heuristic"), (
            f"Unexpected scorer {result.evaluated_by!r}"
        )
        if result.evaluated_by == "heuristic":
            assert result.agent_error, (
                "Fell back to the heuristic scorer without recording why"
            )
    else:
        assert result.evaluated_by == "heuristic", (
            "LLM is unavailable — the agent must fall back to the heuristic "
            f"scorer, but used {result.evaluated_by!r}"
        )

    # Regardless of path, a fully compliant policy must not score near zero.
    assert result.policy_score >= 0.4, (
        f"Fully-compliant policy text scored {result.policy_score:.4f} "
        f"(via {result.evaluated_by}); missing={result.missing_disclosures}"
    )
    print(f"  [PASS] PolicyAgent returned a valid result via {result.evaluated_by}.")


@pytest.mark.asyncio
async def test_policy_agent_non_compliant():
    """Empty policy texts — assert is_compliant=False, policy_score=0.0."""
    from razorshield_backend.agents.policy_agent import PolicyAgent
    from razorshield_backend.config import get_settings

    agent = PolicyAgent(settings=get_settings())
    result = await agent.evaluate(PolicyTexts(terms="", privacy="", refund="", contact=""))

    print(f"\n  is_compliant={result.is_compliant} policy_score={result.policy_score}")

    assert result.is_compliant is False
    assert result.policy_score == 0.0
    assert len(result.missing_disclosures) > 0
    # No text means no LLM call should ever have been made.
    assert result.evaluated_by == "none"
    print("  [PASS] PolicyAgent flagged empty policy without calling the LLM.")


# ── Catalog Agent (needs the database) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_catalog_agent_clean(safe_scrape_result, require_db):
    """Safe products — assert has_prohibited_items=False."""
    from razorshield_backend.agents.catalog_agent import CatalogAgent, CatalogResult
    from razorshield_backend.config import get_settings

    agent = CatalogAgent(settings=get_settings())
    result = await agent.evaluate(safe_scrape_result.products)

    print(f"\n  has_prohibited_items={result.has_prohibited_items}")
    print(f"  catalog_score={result.catalog_score:.4f}")
    print(f"  flagged={[f.product_title for f in result.flagged_items]}")
    print(f"  checked_via_vectors={result.checked_via_vectors}")

    assert isinstance(result, CatalogResult)
    assert 0.0 <= result.catalog_score <= 1.0
    assert result.has_prohibited_items is False, (
        f"Safe products incorrectly flagged: "
        f"{[(f.product_title, f.matched_pattern, f.similarity_score) for f in result.flagged_items]}"
    )
    print("  [PASS] CatalogAgent cleared safe products.")


@pytest.mark.asyncio
async def test_catalog_agent_prohibited_flag(prohibited_scrape_result, require_db):
    """Prohibited products — assert has_prohibited_items=True."""
    from razorshield_backend.agents.catalog_agent import CatalogAgent
    from razorshield_backend.config import get_settings

    agent = CatalogAgent(settings=get_settings())
    result = await agent.evaluate(prohibited_scrape_result.products)

    print(f"\n  has_prohibited_items={result.has_prohibited_items}")
    print(f"  catalog_score={result.catalog_score:.4f}")
    for fi in result.flagged_items:
        print(f"    → {fi.product_title!r} ({fi.matched_category}) sim={fi.similarity_score:.4f}")

    assert result.has_prohibited_items is True, (
        "Opioids, counterfeit goods, and firearm accessories should be flagged.\n"
        f"catalog_score={result.catalog_score:.4f} "
        f"checked_via_vectors={result.checked_via_vectors}"
    )
    assert len(result.flagged_items) >= 1
    print(f"  [PASS] CatalogAgent flagged {len(result.flagged_items)} prohibited items.")


@pytest.mark.asyncio
async def test_catalog_agent_empty_catalog_is_clean():
    """A merchant with no extractable products is not, by itself, risky."""
    from razorshield_backend.agents.catalog_agent import CatalogAgent
    from razorshield_backend.config import get_settings

    result = await CatalogAgent(settings=get_settings()).evaluate([])
    assert result.has_prohibited_items is False
    assert result.catalog_score == 1.0
    print("\n  [PASS] Empty catalog scored 1.0 without touching the DB.")


def test_keyword_fallback_is_deterministic(prohibited_scrape_result):
    """
    The keyword fallback must report the same matched pattern every run.

    It previously iterated a `set`, so which keyword got attributed to a product
    varied between processes — unacceptable for an auditable risk verdict.
    """
    from razorshield_backend.agents.catalog_agent import CatalogAgent
    from razorshield_backend.config import get_settings

    agent = CatalogAgent(settings=get_settings())
    first = agent._keyword_fallback(prohibited_scrape_result.products)
    second = agent._keyword_fallback(prohibited_scrape_result.products)

    assert [(f.product_title, f.matched_pattern) for f in first] == [
        (f.product_title, f.matched_pattern) for f in second
    ]
    assert first, "Keyword fallback found nothing in an obviously prohibited catalog"
    print(f"\n  [PASS] Keyword fallback deterministic ({len(first)} matches).")


def test_vector_literal_rejects_non_finite_values():
    """NaN/inf must raise rather than being interpolated into SQL."""
    import math

    from razorshield_backend.agents.catalog_agent import to_vector_literal

    assert to_vector_literal([0.5, -0.25]) == "[0.500000,-0.250000]"
    for bad in (float("nan"), math.inf, -math.inf):
        with pytest.raises(ValueError):
            to_vector_literal([0.1, bad])
    with pytest.raises(ValueError):
        to_vector_literal([])


# ── Orchestrator — scoring logic (no I/O) ─────────────────────────────────────

def test_domain_risk_curve_is_monotonic():
    """Older domains must never score as riskier than newer ones."""
    from razorshield_backend.agents.orchestrator import _compute_domain_risk
    from razorshield_backend.scrapers.whois_client import DomainInspection

    def risk(age: int) -> float:
        return _compute_domain_risk(
            DomainInspection("d.com", age, True, 90, "R", None)
        )

    ages = [0, 2, 10, 45, 200, 400, 1000, 5000]
    scores = [risk(a) for a in ages]
    assert scores == sorted(scores, reverse=True), f"Non-monotonic domain risk: {list(zip(ages, scores))}"
    assert risk(-1) == 60.0, "Unknown domain age should map to elevated uncertainty"
    assert all(0.0 <= s <= 100.0 for s in scores)
    print(f"\n  [PASS] Domain risk curve monotonic: {list(zip(ages, scores))}")


@pytest.mark.parametrize(
    "score,expected",
    [(0, "SAFE"), (34.9, "SAFE"), (35, "MANUAL_REVIEW"),
     (64.9, "MANUAL_REVIEW"), (65, "HIGH_RISK"), (100, "HIGH_RISK")],
)
def test_tier_boundaries(score, expected):
    """Tier thresholds must match the documented 35 / 65 cut-points."""
    from razorshield_backend.agents.orchestrator import _determine_tier

    assert _determine_tier(score).value == expected


def test_guardrail_b_reason_is_stable():
    """
    The guardrail reason string must be identical across runs for identical
    findings — it is written into the immutable audit record.
    """
    from razorshield_backend.agents.catalog_agent import CatalogResult, FlaggedItem
    from razorshield_backend.agents.orchestrator import _compute_risk_score
    from razorshield_backend.agents.policy_agent import PolicyResult
    from razorshield_backend.scrapers.whois_client import DomainInspection

    catalog = CatalogResult(
        has_prohibited_items=True,
        catalog_score=0.4,
        flagged_items=[
            FlaggedItem("A", "narcotics", "p", 0.9),
            FlaggedItem("B", "firearms", "p", 0.9),
            FlaggedItem("C", "counterfeit_goods", "p", 0.9),
        ],
    )
    policy = PolicyResult(is_compliant=True, policy_score=1.0)
    domain = DomainInspection("d.com", 2000, True, 90, "R", None)

    reasons = {_compute_risk_score(policy, catalog, domain)[2] for _ in range(5)}
    assert len(reasons) == 1, f"Guardrail reason varied across runs: {reasons}"
    print(f"\n  [PASS] Stable guardrail reason: {reasons.pop()}")


# ── Orchestrator — end-to-end scoring ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_guardrail_a(prohibited_scrape_result, newborn_domain_info):
    """Guardrail A: domain < 3 days + policy_score < 0.4 → HIGH_RISK (score >= 90)."""
    from razorshield_backend.agents.orchestrator import score_from_raw_data

    report = await score_from_raw_data(
        url="https://brand-new-scam.xyz",
        scrape_result=prohibited_scrape_result,
        domain_info=newborn_domain_info,
        persist=False,
    )

    print(f"\n  risk_score={report.risk_score} tier={report.risk_tier}")
    print(f"  guardrail={report.guardrail_triggered} reason={report.guardrail_reason!r}")

    assert report.guardrail_triggered is True
    assert report.risk_score >= 90.0
    assert report.risk_tier == "HIGH_RISK"
    assert report.guardrail_reason
    print(f"  [PASS] Guardrail A fired. score={report.risk_score}")


@pytest.mark.asyncio
async def test_orchestrator_guardrail_b(prohibited_scrape_result, established_domain_info, require_db):
    """Guardrail B: has_prohibited_items=True → HIGH_RISK (score >= 88)."""
    from razorshield_backend.agents.orchestrator import score_from_raw_data

    report = await score_from_raw_data(
        url="https://bad-actor.example.com",
        scrape_result=prohibited_scrape_result,
        domain_info=established_domain_info,
        persist=False,
    )

    print(f"\n  risk_score={report.risk_score} tier={report.risk_tier}")
    print(f"  guardrail={report.guardrail_triggered} reason={report.guardrail_reason!r}")

    assert report.guardrail_triggered is True
    assert report.risk_score >= 88.0
    assert report.risk_tier == "HIGH_RISK"
    print(f"  [PASS] Guardrail B fired. score={report.risk_score}")


@pytest.mark.asyncio
async def test_orchestrator_safe_merchant(safe_scrape_result, established_domain_info, require_db):
    """A compliant merchant on an established domain must not be HIGH_RISK."""
    from razorshield_backend.agents.orchestrator import score_from_raw_data

    report = await score_from_raw_data(
        url="https://safe-merchant.example.com",
        scrape_result=safe_scrape_result,
        domain_info=established_domain_info,
        persist=False,
    )

    print(f"\n  risk_score={report.risk_score} tier={report.risk_tier}")
    print(f"  policy_score={report.policy_result.get('policy_score')} "
          f"(via {report.policy_result.get('evaluated_by')})")
    print(f"  catalog_score={report.catalog_result.get('catalog_score')}")
    print(f"  fully_analyzed={report.fully_analyzed} llm_narrative={report.llm_narrative}")

    assert report.guardrail_triggered is False, f"reason={report.guardrail_reason!r}"
    assert report.risk_tier in ("SAFE", "MANUAL_REVIEW"), (
        f"Safe merchant scored {report.risk_score} → {report.risk_tier}"
    )
    assert len(report.audit_trail) > 50, "audit_trail is too short to be useful"
    assert report.scan_id
    print(f"  [PASS] Safe merchant scored {report.risk_score:.1f} ({report.risk_tier}).")


@pytest.mark.asyncio
async def test_report_declares_degraded_analysis(safe_scrape_result, established_domain_info, require_db, llm_available):
    """
    The report must state whether every signal came from its primary path.

    Without this, a verdict produced with the LLM down and pgvector unseeded is
    indistinguishable from a full analysis.
    """
    from razorshield_backend.agents.orchestrator import score_from_raw_data

    report = await score_from_raw_data(
        url="https://safe-merchant.example.com",
        scrape_result=safe_scrape_result,
        domain_info=established_domain_info,
        persist=False,
    )

    quality = report.findings.get("analysis_quality")
    assert quality is not None, "findings must include an analysis_quality block"
    assert isinstance(quality["fully_analyzed"], bool)
    assert isinstance(quality["degraded_reasons"], list)
    assert quality["fully_analyzed"] == (not quality["degraded_reasons"])

    if not llm_available:
        assert quality["fully_analyzed"] is False, (
            "LLM is unavailable, so the report must not claim a full analysis"
        )
        assert any("narrative" in r or "policy" in r for r in quality["degraded_reasons"])

    print(f"\n  fully_analyzed={quality['fully_analyzed']}")
    print(f"  degraded_reasons={quality['degraded_reasons']}")
    print("  [PASS] Report declares its own analysis quality.")


# ── LLM credential failover ───────────────────────────────────────────────────

def _settings_with_keys(*keys: str):
    """Clone the real settings with a specific key list."""
    from razorshield_backend.config import get_settings

    base = get_settings()
    return base.model_copy(
        update={
            "openrouter_api_key": keys[0],
            "openrouter_fallback_api_key": ",".join(keys[1:]),
        }
    )


def test_settings_build_ordered_deduplicated_key_list():
    s = _settings_with_keys("sk-primary", "sk-fallback-a", "sk-fallback-b")
    assert s.openrouter_api_keys == ["sk-primary", "sk-fallback-a", "sk-fallback-b"]

    # Duplicates and blanks must not create phantom credentials.
    dup = s.model_copy(
        update={"openrouter_fallback_api_key": " sk-primary , , sk-fallback-a "}
    )
    assert dup.openrouter_api_keys == ["sk-primary", "sk-fallback-a"]

    none = s.model_copy(update={"openrouter_fallback_api_key": ""})
    assert none.openrouter_api_keys == ["sk-primary"]


@pytest.mark.parametrize(
    "message,expect_key_specific",
    [
        ('{"error":{"message":"Insufficient credits.","code":402}}', True),
        ('{"error":{"message":"Invalid API key","code":401}}', True),
        ('{"error":{"message":"Forbidden","code":403}}', True),
        ('{"error":{"message":"quota exceeded","code":429}}', True),
        # Not the credential's fault — must NOT burn the fallback keys.
        ('{"error":{"message":"model is not a valid model id","code":404}}', False),
        ('{"error":{"message":"Bad request: messages required","code":400}}', False),
    ],
)
def test_key_specific_classification(message, expect_key_specific):
    """
    Only credential failures should trigger failover. Rotating through every key
    on a malformed request would just repeat the same error N times.
    """
    from razorshield_backend.agents.llm import classify_error

    verdict = classify_error(RuntimeError(message))
    assert verdict.key_specific is expect_key_specific, (
        f"{message[:50]!r} → key_specific={verdict.key_specific}, expected {expect_key_specific}"
    )


@pytest.mark.asyncio
async def test_failover_switches_to_fallback_key_on_exhausted_primary():
    """
    A primary key that is out of credits must hand off to the fallback key and
    the request must still succeed.
    """
    import razorshield_backend.agents.llm as llm_module
    from razorshield_backend.agents.llm import LLMClient

    client = LLMClient(_settings_with_keys("sk-primary", "sk-fallback"))
    seen: list[str] = []

    async def _fake(**kwargs):
        seen.append(kwargs["api_key"])
        if kwargs["api_key"] == "sk-primary":
            raise RuntimeError('{"error":{"message":"Insufficient credits.","code":402}}')

        class _Msg:
            content = "recovered"

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()

    original = llm_module.litellm.acompletion
    llm_module.litellm.acompletion = _fake
    try:
        out = await client.complete(system_prompt="s", user_message="u")
        assert out == "recovered", f"Expected fallback to answer, got {out!r}"
        assert seen == ["sk-primary", "sk-fallback"], f"Key order was {seen}"

        # The working key is remembered — no repeat call on the dead primary.
        seen.clear()
        out2 = await client.complete(system_prompt="s", user_message="u")
        assert out2 == "recovered"
        assert seen == ["sk-fallback"], (
            f"Second call should skip the exhausted primary, but tried {seen}"
        )
    finally:
        llm_module.litellm.acompletion = original

    status = client.key_status()
    assert status[0]["status"] == "exhausted"
    assert status[1]["status"] == "available"
    assert status[1]["active"] is True
    print(f"\n  [PASS] Failover: primary exhausted, active key = {status[1]['label']}")


@pytest.mark.asyncio
async def test_failover_reports_when_every_key_is_exhausted():
    """When no key can serve the request the client must say so explicitly."""
    import razorshield_backend.agents.llm as llm_module
    from razorshield_backend.agents.llm import LLMClient, LLMUnavailable

    client = LLMClient(_settings_with_keys("sk-a", "sk-b"))
    calls: list[str] = []

    async def _fake(**kwargs):
        calls.append(kwargs["api_key"])
        raise RuntimeError('{"error":{"message":"Insufficient credits.","code":402}}')

    original = llm_module.litellm.acompletion
    llm_module.litellm.acompletion = _fake
    try:
        with pytest.raises(LLMUnavailable) as exc:
            await client.complete(system_prompt="s", user_message="u")
        assert calls == ["sk-a", "sk-b"], f"Both keys should be tried once each, got {calls}"
        assert "exhausted" in str(exc.value).lower(), f"Unhelpful reason: {exc.value}"

        # Breaker is now open — no further provider traffic.
        calls.clear()
        with pytest.raises(LLMUnavailable):
            await client.complete(system_prompt="s", user_message="u")
        assert calls == [], f"Breaker should have blocked the call, but tried {calls}"
    finally:
        llm_module.litellm.acompletion = original

    print("\n  [PASS] All keys exhausted reported once, then short-circuited.")


@pytest.mark.asyncio
async def test_request_fault_does_not_burn_fallback_keys():
    """A bad model slug must fail on the first key, not rotate through all."""
    import razorshield_backend.agents.llm as llm_module
    from razorshield_backend.agents.llm import LLMClient, LLMUnavailable

    client = LLMClient(_settings_with_keys("sk-a", "sk-b", "sk-c"))
    calls: list[str] = []

    async def _fake(**kwargs):
        calls.append(kwargs["api_key"])
        raise RuntimeError('{"error":{"message":"xyz is not a valid model id","code":404}}')

    original = llm_module.litellm.acompletion
    llm_module.litellm.acompletion = _fake
    try:
        with pytest.raises(LLMUnavailable):
            await client.complete(system_prompt="s", user_message="u")
    finally:
        llm_module.litellm.acompletion = original

    assert calls == ["sk-a"], (
        f"A request-level fault must not rotate keys, but tried {calls}"
    )
    print("\n  [PASS] Request fault stopped at the first key.")


def test_key_status_never_leaks_key_material():
    """
    /api/v1/readiness returns this to the browser, so it must be redacted.
    """
    from razorshield_backend.agents.llm import LLMClient, redact_key

    secret = "sk-or-v1-abcdef0123456789abcdef0123456789"
    client = LLMClient(_settings_with_keys(secret, "sk-or-v1-999888777666555444333222111000"))

    for entry in client.key_status():
        assert secret not in entry["key"], "Full API key leaked into key_status()"
        assert entry["key"].count("…") == 1, f"Key not redacted: {entry['key']}"

    assert redact_key("") == "<unset>"
    assert redact_key("short") == "<short-key>"
    print("\n  [PASS] Key status is redacted.")


# ── Blocked sites are unverified, not non-compliant ───────────────────────────

@pytest.mark.asyncio
async def test_blocked_scrape_yields_inconclusive_policy():
    """
    A site that serves a bot challenge tells us nothing about its compliance.
    The agent must say so rather than returning a measured-looking 0.0.
    """
    from razorshield_backend.agents.policy_agent import PolicyAgent
    from razorshield_backend.config import get_settings

    agent = PolicyAgent(settings=get_settings())
    result = await agent.evaluate(
        PolicyTexts(), blocked=True, block_reason="AWS WAF bot challenge"
    )

    assert result.inconclusive is True
    assert result.evaluated_by == "blocked"
    assert "could not be verified" in result.missing_disclosures[0].lower()
    # It must NOT read like a measured non-compliance finding.
    assert "no policy pages accessible" not in result.missing_disclosures[0].lower()
    print(f"\n  [PASS] Blocked scrape → inconclusive: {result.missing_disclosures[0]}")


@pytest.mark.asyncio
async def test_unblocked_empty_policy_is_still_a_real_zero():
    """A reachable site that publishes nothing is genuinely non-compliant."""
    from razorshield_backend.agents.policy_agent import PolicyAgent
    from razorshield_backend.config import get_settings

    result = await PolicyAgent(settings=get_settings()).evaluate(PolicyTexts(), blocked=False)
    assert result.inconclusive is False
    assert result.policy_score == 0.0
    assert result.evaluated_by == "none"


def test_inconclusive_policy_is_excluded_from_the_weighted_score():
    """
    An unverifiable policy signal must not contribute a flat 40-point penalty.

    This is the amazon.com failure: a WAF challenge produced policy 0/100, which
    added 40 risk points purely for being well defended and pushed a blue-chip
    merchant to MANUAL_REVIEW. The remaining weights are renormalised instead.
    """
    from razorshield_backend.agents.catalog_agent import CatalogResult
    from razorshield_backend.agents.orchestrator import _compute_risk_score
    from razorshield_backend.agents.policy_agent import PolicyResult
    from razorshield_backend.scrapers.whois_client import DomainInspection

    clean_catalog = CatalogResult(has_prohibited_items=False, catalog_score=1.0)
    old_domain = DomainInspection("amazon.com", 10_000, True, 90, "MarkMonitor", None)

    blocked = PolicyResult(
        is_compliant=False, policy_score=0.0, evaluated_by="blocked", inconclusive=True
    )
    scored_zero = PolicyResult(is_compliant=False, policy_score=0.0, evaluated_by="none")

    blocked_score, _, _ = _compute_risk_score(blocked, clean_catalog, old_domain)
    zero_score, _, _ = _compute_risk_score(scored_zero, clean_catalog, old_domain)

    print(f"\n  inconclusive → {blocked_score:.1f}   scored-zero → {zero_score:.1f}")
    assert blocked_score < zero_score, (
        "An unverifiable policy must not be penalised as heavily as a verified absence"
    )
    # With a clean catalog and an old domain, nothing measured is risky.
    assert blocked_score < 35, f"Blocked-but-clean merchant scored {blocked_score}"


@pytest.mark.asyncio
async def test_blocked_merchant_is_floored_at_manual_review(established_domain_info):
    """
    We could not verify the merchant, so the verdict must not be SAFE — but it
    must not be HIGH_RISK either, since nothing incriminating was found.
    """
    from razorshield_backend.agents.orchestrator import score_from_raw_data
    from razorshield_backend.scrapers.browser import MerchantScrapeResult

    blocked_scrape = MerchantScrapeResult(
        url="https://amazon.com",
        title="",
        meta_description="",
        homepage_text="",
        policy_texts=PolicyTexts(),
        products=[],
        blocked=True,
        block_reason="AWS WAF bot challenge",
        http_status=202,
        error="Site blocked automated inspection (AWS WAF bot challenge)",
    )

    report = await score_from_raw_data(
        url="https://amazon.com",
        scrape_result=blocked_scrape,
        domain_info=established_domain_info,
        persist=False,
    )

    print(f"\n  risk={report.risk_score} tier={report.risk_tier}")
    print(f"  policy inconclusive={report.policy_result['inconclusive']}")
    print(f"  degraded={report.findings['analysis_quality']['degraded_reasons']}")

    assert report.risk_tier == "MANUAL_REVIEW", (
        f"A merchant we could not inspect must be reviewed, not auto-decided "
        f"(got {report.risk_tier})"
    )
    assert report.policy_result["inconclusive"] is True
    assert report.fully_analyzed is False
    assert any("blocked" in r.lower() for r in report.findings["analysis_quality"]["degraded_reasons"])
    # The narrative must not assert non-compliance.
    assert "non-compliant" not in report.audit_trail.lower(), (
        "Audit narrative asserted non-compliance for a site we never read"
    )
    print("  [PASS] Blocked merchant floored at MANUAL_REVIEW, not called non-compliant.")
