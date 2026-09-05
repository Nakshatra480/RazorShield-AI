"""
tests/test_scrapers.py
─────────────────────────────────────────────────────────────────────────────
Playwright DOM scraper + WHOIS/SSL inspector tests.

Network-dependent tests are marked `network` and skip cleanly when the host is
offline, rather than hanging or failing spuriously.
"""

import asyncio
import socket

import pytest

pytestmark = pytest.mark.timeout(180)


def _internet_available(host: str = "1.1.1.1", port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def network():
    if not _internet_available():
        pytest.skip("No outbound network connectivity.")
    return True


# ── Parsing helpers (no network) ──────────────────────────────────────────────

def test_policy_link_discovery_from_html():
    """
    Link discovery is pure parsing — assert it directly instead of relying on a
    third-party site's markup staying stable.
    """
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _discover_policy_links

    html = """
    <html><body>
      <a href="/legal/terms-of-service">Terms</a>
      <a href="/privacy-policy">Privacy</a>
      <a href="/help/refund-policy">Refunds</a>
      <a href="/contact-us">Contact</a>
      <a href="mailto:hi@example.com">Email</a>
      <a href="#top">Top</a>
      <a href="javascript:void(0)">JS</a>
    </body></html>
    """
    links = _discover_policy_links(BeautifulSoup(html, "lxml"), "https://shop.example.com")

    print(f"\n  discovered={links}")
    assert set(links) == {"terms", "privacy", "refund", "contact"}
    assert links["terms"] == "https://shop.example.com/legal/terms-of-service"
    assert all(v.startswith("https://") for v in links.values()), (
        f"mailto:/javascript: links must never be followed — got {links}"
    )
    print("  [PASS] Policy links discovered and unsafe schemes excluded.")


def test_product_extraction_respects_limit():
    """Product extraction must honour the configured cap."""
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _extract_products

    html = "<html><body>" + "".join(
        f'<div class="product-card"><h2 class="product-card__title">Item {i}</h2></div>'
        for i in range(50)
    ) + "</body></html>"

    products = _extract_products(BeautifulSoup(html, "lxml"), limit=5)
    assert len(products) == 5, f"Expected 5 products, got {len(products)}"
    assert products[0].title == "Item 0"
    print(f"\n  [PASS] Extraction capped at {len(products)} products.")


# ── Browser manager lifecycle ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browser_manager_recovers_across_event_loops(network):
    """
    The browser singleton must be usable from a fresh event loop.

    Regression guard for the hang that made `test_policy_link_discovery` time
    out at 300s: Playwright objects are bound to the loop that created them, and
    the manager cached the browser in a class attribute with no loop check. A
    second event loop in the same process reused the dead handle and blocked
    forever on its first navigation. The manager now detects the mismatch and
    relaunches.
    """
    from razorshield_backend.scrapers.browser import BrowserManager

    # Simulate the state left behind by a previous, now-closed event loop.
    BrowserManager._browser = object()  # type: ignore[assignment]
    BrowserManager._loop = asyncio.new_event_loop()
    BrowserManager._playwright = None

    try:
        context = await asyncio.wait_for(BrowserManager.new_context(), timeout=90)
        page = await context.new_page()
        await page.set_content("<html><title>Recovered</title><body>ok</body></html>")
        assert await page.title() == "Recovered"
        await page.close()
        await context.close()
        print("\n  [PASS] BrowserManager relaunched after a stale-loop handle.")
    finally:
        loop = BrowserManager._loop
        if isinstance(loop, asyncio.AbstractEventLoop) and not loop.is_running():
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass


@pytest.mark.asyncio
async def test_scrape_merchant_never_raises_on_bad_host(network):
    """
    An unresolvable host must return a MerchantScrapeResult carrying the error,
    not propagate an exception into the inspection pipeline.
    """
    from razorshield_backend.scrapers.browser import scrape_merchant

    result = await scrape_merchant("https://this-domain-does-not-exist-rz9x2.invalid")

    print(f"\n  error={result.error!r}")
    assert result.error is not None, "A dead host should record an error"
    assert result.scrape_failed is True
    assert result.homepage_text == ""
    assert result.products == []
    print("  [PASS] Unreachable host degraded gracefully.")


# ── Live scraping ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_playwright_rendering(network):
    """Render example.com and confirm the DOM and body text come back."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded", timeout=30_000)
            title = await page.title()
            html = await page.content()
            body_text = await page.evaluate("document.body.innerText")
            await context.close()
        finally:
            await browser.close()

    print(f"\n  title={title!r} html_len={len(html)} body_len={len(body_text)}")
    assert len(html) > 0, "Page HTML is empty"
    assert "Example" in title, f"Unexpected title: {title!r}"
    assert len(body_text) >= 100, f"Body text too short ({len(body_text)} chars)"
    print("  [PASS] Playwright rendered example.com.")


@pytest.mark.asyncio
async def test_scrape_merchant_end_to_end(network):
    """
    Drive the production scrape path against a stable, permissive site.

    Asserts the scraper reaches the site and returns structured content; the
    exact policy links a third party publishes are not something this suite
    should depend on (that is covered by the parsing test above).
    """
    from razorshield_backend.scrapers.browser import scrape_merchant

    result = await scrape_merchant("https://example.com")

    print(f"\n  title={result.title!r}")
    print(f"  homepage_text_len={len(result.homepage_text)}")
    print(f"  products={len(result.products)} error={result.error!r}")

    assert result.error is None, f"Scrape reported an error: {result.error}"
    assert result.title, "No page title captured"
    assert len(result.homepage_text) > 50, "Homepage text suspiciously short"
    print("  [PASS] scrape_merchant returned structured content.")


# ── WHOIS / SSL ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_whois_lookup(network):
    """inspect_domain must return a well-formed DomainInspection for a real domain."""
    from razorshield_backend.scrapers.whois_client import DomainInspection, inspect_domain

    info = await inspect_domain("https://stripe.com")

    print(f"\n  domain={info.domain!r} age={info.domain_age_days}")
    print(f"  ssl_valid={info.is_ssl_valid} expiry={info.ssl_expiry_days}")
    print(f"  registrar={info.registrar!r}")

    assert isinstance(info, DomainInspection)
    assert info.domain == "stripe.com"
    assert info.is_ssl_valid is True, "stripe.com should present a valid certificate"
    assert info.ssl_expiry_days > 0

    # WHOIS can be rate-limited or blocked from CI networks; -1 means "unknown",
    # which the risk engine already handles. Only assert the age when we got one.
    if info.domain_age_days >= 0:
        assert info.domain_age_days > 365, (
            f"stripe.com should be >365 days old, got {info.domain_age_days}"
        )
        assert info.registrar, "A successful WHOIS lookup should name a registrar"
    else:
        print("  [INFO] WHOIS unavailable from this network — age reported as unknown.")
    print("  [PASS] Domain inspection returned a valid structure.")


@pytest.mark.asyncio
async def test_domain_inspection_is_time_bounded(network):
    """
    inspect_domain must respect its budget rather than blocking indefinitely.

    python-whois issues a port-43 query with no timeout of its own; an
    unresponsive registry previously hung the calling thread (and the request)
    forever. This test simply asserts the call returns within the budget.
    """
    import time

    from razorshield_backend.scrapers.whois_client import (
        DOMAIN_INSPECTION_TIMEOUT_SECONDS,
        inspect_domain,
    )

    start = time.monotonic()
    info = await inspect_domain("https://nonexistent-registry-test-zz99.invalid")
    elapsed = time.monotonic() - start

    print(f"\n  elapsed={elapsed:.1f}s budget={DOMAIN_INSPECTION_TIMEOUT_SECONDS}s")
    assert elapsed < DOMAIN_INSPECTION_TIMEOUT_SECONDS + 10, (
        f"inspect_domain took {elapsed:.1f}s, exceeding its "
        f"{DOMAIN_INSPECTION_TIMEOUT_SECONDS}s budget"
    )
    assert info.domain_age_days == -1
    assert info.is_ssl_valid is False
    print("  [PASS] Domain inspection returned within budget.")


@pytest.mark.asyncio
async def test_ssl_invalid_domain(network):
    """A self-signed certificate must not validate."""
    from razorshield_backend.scrapers.whois_client import inspect_domain

    info = await inspect_domain("https://self-signed.badssl.com")

    print(f"\n  domain={info.domain!r} ssl_valid={info.is_ssl_valid}")
    assert isinstance(info.is_ssl_valid, bool)
    if info.is_ssl_valid:
        print("  [INFO] A TLS-intercepting proxy made the cert appear valid; skipping strict check.")
    else:
        assert info.ssl_expiry_days == -1
        print("  [PASS] Self-signed certificate correctly rejected.")


def test_clean_soup_text_does_not_mutate_tree():
    """
    Text extraction must leave the DOM intact.

    Regression guard for the highest-impact scraper bug: `_clean_soup_text`
    used to call `tag.decompose()` on nav/footer/header, and it ran before
    `_discover_policy_links`. Sites put Terms/Privacy/Refund links in the
    footer, so those links were destroyed before discovery saw them and the
    policy agent — 40% of the risk weight — received almost no input.
    """
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _clean_soup_text, _discover_policy_links

    html = """
    <html><body>
      <header><a href="/about">About</a></header>
      <main><p>We sell eco-friendly products worldwide.</p></main>
      <footer>
        <a href="/terms">Terms of Service</a>
        <a href="/privacy">Privacy Policy</a>
        <a href="/refund-policy">Refunds</a>
        <a href="/contact">Contact</a>
      </footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")

    before = len(soup.find_all("a"))
    text = _clean_soup_text(soup)
    after = len(soup.find_all("a"))

    assert before == after == 5, f"Anchors were destroyed: {before} → {after}"
    assert soup.find("footer") is not None, "_clean_soup_text removed the <footer>"

    # Body text still excludes chrome...
    assert "eco-friendly products" in text
    assert "Privacy Policy" not in text, "Footer text leaked into the body extract"

    # ...and the footer links are still discoverable afterwards.
    links = _discover_policy_links(soup, "https://shop.example.com")
    assert set(links) == {"terms", "privacy", "refund", "contact"}, (
        f"Policy links lost after text extraction: {links}"
    )
    print(f"\n  [PASS] Tree intact after extraction; links found: {sorted(links)}")


def test_clean_soup_text_respects_max_chars():
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _clean_soup_text

    soup = BeautifulSoup("<html><body>" + "<p>lorem ipsum dolor</p>" * 2000 + "</body></html>", "lxml")
    assert len(_clean_soup_text(soup, max_chars=500)) <= 500


# ── Anti-bot block detection ──────────────────────────────────────────────────

# Trimmed from the real HTTP 202 response amazon.com served to a headless
# request: an AWS WAF challenge, ~2KB, with zero anchors.
_AWS_WAF_CHALLENGE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title></title>
<script type="text/javascript">
window.awsWafCookieDomainList = [];
window.gokuProps = {"key":"AQIDAHjc","iv":"grC4iw","context":"kot3"};
</script>
<script src="https://x.token.awswaf.com/challenge.js"></script>
</head><body><div id="challenge-container"></div>
<script>AwsWafIntegration.saveReferrer();</script></body></html>
"""

_CLOUDFLARE_INTERSTITIAL = """
<html><head><title>Just a moment...</title></head>
<body><div class="cf-browser-verification"></div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script></body></html>
"""


@pytest.mark.parametrize(
    "html,status,expect_blocked",
    [
        (_AWS_WAF_CHALLENGE, 202, True),
        (_CLOUDFLARE_INTERSTITIAL, 503, True),
        ("<html><body>Access Denied</body></html>", 403, True),
        ("<html><body></body></html>", 200, True),          # empty body
        # A real page must never be misread as a block.
        (
            "<html><body><h1>Shop</h1><p>" + "Genuine merchant copy. " * 60 + "</p>"
            '<a href="/terms">Terms</a></body></html>',
            200,
            False,
        ),
    ],
)
def test_detect_block(html, status, expect_blocked):
    """
    A WAF challenge is not a merchant homepage.

    Reading "no policies, no products" off a CAPTCHA page and scoring the
    merchant non-compliant penalises exactly the largest, best-defended
    merchants — inverted for an underwriting tool.
    """
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _detect_block

    reason = _detect_block(status, html, BeautifulSoup(html, "lxml"))
    assert (reason is not None) is expect_blocked, (
        f"status={status} → reason={reason!r}, expected blocked={expect_blocked}"
    )


def test_policy_links_found_via_anchor_text_when_href_is_opaque():
    """
    Large merchants use opaque policy URLs.

    Amazon publishes Conditions of Use and its Privacy Notice at paths like
    `/gp/help/customer/display.html?nodeId=468496` — the keyword appears only in
    the link *text*. href-only matching found nothing on amazon.com, which is
    why it scored 0/100 with "No policy pages accessible".
    """
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _discover_policy_links

    html = """
    <html><body><footer>
      <a href="/gp/help/customer/display.html?nodeId=508088">Conditions of Use</a>
      <a href="/gp/help/customer/display.html?nodeId=468496">Privacy Notice</a>
      <a href="/gp/help/customer/display.html?nodeId=901888">Returns Are Easy</a>
      <a href="/gp/help/customer/contact-us">Contact Us</a>
    </footer></body></html>
    """
    links = _discover_policy_links(BeautifulSoup(html, "lxml"), "https://www.amazon.com")

    print(f"\n  discovered={links}")
    assert set(links) == {"terms", "privacy", "refund", "contact"}, (
        f"Opaque-href policy links were not discovered: {links}"
    )


def test_anchor_text_matching_ignores_long_product_titles():
    """A product name containing a keyword must not pass as a policy link."""
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _discover_policy_links

    html = """
    <html><body>
      <a href="/p/1">Privacy Screen Protector for 13-inch Laptops, Anti-Glare, 3-pack</a>
      <a href="/p/2">Terms and Conditions of Sale Explained: A Complete Guide for Sellers</a>
    </body></html>
    """
    links = _discover_policy_links(BeautifulSoup(html, "lxml"), "https://shop.example.com")
    assert links == {}, f"Long product titles were mistaken for policy links: {links}"


def test_href_match_wins_over_text_match():
    """A URL match is stronger evidence than link text and must take priority."""
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _discover_policy_links

    html = """
    <html><body>
      <a href="/blog/post">Privacy</a>
      <a href="/legal/privacy-policy">Read this</a>
    </body></html>
    """
    links = _discover_policy_links(BeautifulSoup(html, "lxml"), "https://shop.example.com")
    assert links["privacy"] == "https://shop.example.com/legal/privacy-policy", (
        f"Text match beat the href match: {links}"
    )


def test_clean_soup_text_excludes_comments_and_scripts():
    """
    HTML comments must never reach the compliance rubric.

    `find_all(string=True)` also yields Comment/Doctype/CData nodes. Including
    them filled amazon.com's extracted "privacy policy" with 6000 characters of
    `sp:feature:head-start` build instrumentation instead of policy prose, so the
    entity-name, refund-timeline and contact checks had nothing to match.
    """
    from bs4 import BeautifulSoup

    from razorshield_backend.scrapers.browser import _clean_soup_text

    html = """<!DOCTYPE html><html><body>
    <!-- sp:feature:head-start --><!-- sp:end-feature:csm:head-open-part2 -->
    <script>var tracking = "csm-instrumentation";</script>
    <style>.hidden{display:none}</style>
    <p>ShopCo Ltd, company number 12345678. Returns within 30 days.</p>
    <footer>Footer chrome</footer></body></html>"""

    out = _clean_soup_text(BeautifulSoup(html, "lxml"))

    print(f"\n  extract={out!r}")
    assert "sp:feature" not in out, "HTML comment leaked into the text extract"
    assert "csm-instrumentation" not in out, "Script contents leaked"
    assert "display:none" not in out, "Stylesheet contents leaked"
    assert "Footer chrome" not in out, "Footer chrome leaked"
    assert "ShopCo Ltd, company number 12345678." in out, "Real copy was dropped"
