"""
razorshield_backend/scrapers/browser.py
────────────────────────────────────────
Async Playwright-based web scraper for merchant homepages and policy pages.

Design:
  - BrowserManager is a process-wide singleton — one Chromium instance is
    launched and reused across all inspections (prevents memory leaks).
  - The singleton is bound to the event loop that created it and is health
    checked before every use, so a crashed or orphaned browser is transparently
    relaunched instead of hanging the caller.
  - Each call to `scrape_merchant` gets its own BrowserContext (separate cookies /
    storage), which is always closed in a finally block.
  - Policy pages are fetched concurrently with asyncio.gather.
  - All navigation failures return empty strings — the agents downstream treat
    missing content as low-compliance signals.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

logger = logging.getLogger(__name__)

# ─── User agent — mimics a real Chrome on Windows ────────────────────────────
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ─── Timeouts (ms) ────────────────────────────────────────────────────────────
_HOMEPAGE_TIMEOUT_MS = 15_000
_POLICY_TIMEOUT_MS = 12_000
# Wall-clock ceiling for one full scrape, so a pathological site cannot hold a
# request open past the homepage + policy timeouts combined.
_SCRAPE_BUDGET_SECONDS = 60.0
_BROWSER_LAUNCH_TIMEOUT_SECONDS = 60.0

# ─── Policy keywords mapped to our internal keys ─────────────────────────────
_POLICY_KEYWORD_MAP: dict[str, list[str]] = {
    "terms": ["terms", "tos", "conditions", "legal"],
    "privacy": ["privacy", "gdpr", "data-policy"],
    "refund": ["refund", "return", "cancellation", "cancel", "money-back"],
    "contact": ["contact", "support", "help", "reach-us"],
}

# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class PolicyTexts:
    """Raw policy page content keyed by policy type."""
    terms: str = ""
    privacy: str = ""
    refund: str = ""
    contact: str = ""


@dataclass
class ProductItem:
    """A single product / listing extracted from the merchant's storefront."""
    title: str
    description: str = ""
    price: str = ""


@dataclass
class MerchantScrapeResult:
    """Complete result from scraping a merchant URL."""
    url: str
    title: str
    meta_description: str
    homepage_text: str
    policy_texts: PolicyTexts
    products: list[ProductItem] = field(default_factory=list)
    error: Optional[str] = None
    # True when the site served an anti-bot challenge / access denial instead of
    # its real content. This is NOT the same as "the merchant has no policies" —
    # see _detect_block.
    blocked: bool = False
    block_reason: Optional[str] = None
    http_status: Optional[int] = None

    @property
    def scrape_failed(self) -> bool:
        return self.error is not None and not self.homepage_text

    @property
    def policy_text_found(self) -> bool:
        p = self.policy_texts
        return any([p.terms, p.privacy, p.refund, p.contact])


# ─── Singleton browser manager ────────────────────────────────────────────────

class BrowserManager:
    """
    Process-level Playwright Chromium singleton.

    Loop affinity
    ─────────────
    Playwright's async objects are bound to the event loop that created them.
    Reusing a browser from a *different* loop does not raise — the call simply
    never completes, because the reply is delivered to a loop that is no longer
    running. The previous implementation cached the browser in a class attribute
    with no loop check, so any second event loop in the same process (pytest
    creates one per test, and so does any script that calls asyncio.run twice)
    hung forever on the first navigation.

    We therefore record the owning loop and treat a mismatch — or a browser that
    has since disconnected — as "no browser", relaunching on demand.
    """

    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _lock: Optional[asyncio.Lock] = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """
        Lazily create the lock inside the running loop.

        A module-import-time asyncio.Lock() binds to whatever loop happens to be
        current at import and misbehaves across loops.
        """
        running = asyncio.get_running_loop()
        if cls._lock is None or cls._loop is not running:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    def _is_usable(cls) -> bool:
        """True only if the cached browser belongs to this loop and is alive."""
        if cls._browser is None:
            return False
        try:
            if cls._loop is not asyncio.get_running_loop():
                return False
        except RuntimeError:
            return False
        return cls._browser.is_connected()

    @classmethod
    async def _discard(cls) -> None:
        """Drop references to a dead/foreign browser without blocking on it."""
        browser, playwright, owner = cls._browser, cls._playwright, cls._loop
        cls._browser = None
        cls._playwright = None
        cls._loop = None

        # Only attempt a clean close when the objects belong to *this* loop;
        # otherwise awaiting them would hang for the same reason.
        try:
            same_loop = owner is asyncio.get_running_loop()
        except RuntimeError:
            same_loop = False
        if not same_loop:
            return

        for closer in (
            getattr(browser, "close", None),
            getattr(playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await asyncio.wait_for(closer(), timeout=10)
            except Exception as exc:  # noqa: BLE001 — teardown must never propagate
                logger.debug("Ignoring browser teardown error: %s", exc)

    @classmethod
    async def initialize(cls) -> None:
        """Launch Chromium if there is no usable instance for this loop."""
        async with cls._get_lock():
            if cls._is_usable():
                return
            if cls._browser is not None:
                logger.info("Discarding stale Playwright browser (dead or foreign event loop).")
                await cls._discard()

            playwright = await async_playwright().start()
            try:
                browser = await asyncio.wait_for(
                    playwright.chromium.launch(
                        headless=True,
                        args=[
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-extensions",
                            "--disable-gpu",
                        ],
                    ),
                    timeout=_BROWSER_LAUNCH_TIMEOUT_SECONDS,
                )
            except Exception:
                await playwright.stop()
                raise

            cls._playwright = playwright
            cls._browser = browser
            cls._loop = asyncio.get_running_loop()
            logger.info("Playwright Chromium browser launched successfully.")

    @classmethod
    async def close(cls) -> None:
        async with cls._get_lock():
            await cls._discard()
            logger.info("Playwright browser closed.")

    @classmethod
    async def is_healthy(cls) -> bool:
        """Readiness probe — does not launch a browser as a side effect."""
        return cls._is_usable()

    @classmethod
    async def new_context(cls) -> BrowserContext:
        """Return a fresh isolated context, relaunching the browser if needed."""
        if not cls._is_usable():
            await cls.initialize()

        browser = cls._browser
        if browser is None:  # pragma: no cover — initialize() raises instead
            raise RuntimeError("Playwright browser is unavailable")

        return await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
            java_script_enabled=True,
        )


# ─── Anti-bot / access-denial detection ───────────────────────────────────────
#
# Large merchants sit behind WAFs that serve a JS challenge instead of the site.
# Amazon, for instance, answers a headless request with HTTP 202 and a ~2KB AWS
# WAF challenge page containing zero anchors. Treating that as "this merchant
# published no policies" is a false-positive generator aimed squarely at the
# most established merchants — precisely inverted for an underwriting tool.
# We detect it so the verdict can say "could not verify" instead of asserting
# non-compliance.

_BLOCK_MARKERS: tuple[tuple[str, str], ...] = (
    ("awswafcookiedomainlist", "AWS WAF bot challenge"),
    ("awswafintegration", "AWS WAF bot challenge"),
    ("challenge-container", "JavaScript bot challenge"),
    ("/cdn-cgi/challenge-platform", "Cloudflare challenge"),
    ("cf-browser-verification", "Cloudflare challenge"),
    ("cf_chl_opt", "Cloudflare challenge"),
    ("just a moment...", "Cloudflare interstitial"),
    ("checking your browser before", "Cloudflare interstitial"),
    ("_incapsula_resource", "Imperva/Incapsula challenge"),
    ("incapsula incident id", "Imperva/Incapsula block"),
    ("perimeterx", "PerimeterX challenge"),
    ("px-captcha", "PerimeterX captcha"),
    ("datadome", "DataDome challenge"),
    ("captcha-delivery.com", "DataDome captcha"),
    ("g-recaptcha", "reCAPTCHA challenge"),
    ("h-captcha", "hCaptcha challenge"),
    ("enter the characters you see below", "Amazon bot check"),
    ("we just need to make sure you're not a robot", "Amazon bot check"),
    ("unusual traffic from your computer network", "automated-traffic block"),
    ("access denied", "access denied"),
    ("request blocked", "request blocked"),
    ("you have been blocked", "access denied"),
)

# Statuses that mean "this is not the real page".
_BLOCK_STATUS = frozenset({202, 401, 403, 405, 406, 429, 503})

# A real merchant homepage is not this small.
_MIN_REAL_PAGE_CHARS = 500


def _detect_block(status, html: str, soup: BeautifulSoup):
    """
    Return a human-readable reason when the response is an anti-bot challenge or
    access denial rather than the merchant's real page; otherwise None.
    """
    lowered = html.lower()

    for marker, reason in _BLOCK_MARKERS:
        if marker in lowered:
            return reason

    anchor_count = len(soup.find_all("a", href=True))

    # Challenge pages are short and link-free, usually with a non-200 status.
    if anchor_count == 0:
        if status is not None and status in _BLOCK_STATUS:
            return f"HTTP {status} with no page content"
        if len(html) < _MIN_REAL_PAGE_CHARS:
            return "empty response body"

    return None


# ─── Internal helpers ─────────────────────────────────────────────────────────

# Structural chrome excluded from body-text extraction (but NOT from link
# discovery — see _clean_soup_text).
_NOISE_TAGS = frozenset(
    {"script", "style", "nav", "footer", "header", "noscript", "aside", "svg", "template"}
)


def _clean_soup_text(soup: BeautifulSoup, max_chars: int = 8000) -> str:
    """
    Return the page's visible body text with chrome and noise removed.

    IMPORTANT: this must not mutate `soup`.

    The previous implementation called `tag.decompose()` on nav/footer/header,
    which edits the tree in place — and it ran *before* `_discover_policy_links`.
    Virtually every site puts its Terms, Privacy, and Refund links in the
    <footer>, so those links were destroyed before discovery ever saw them. The
    policy agent therefore received little or no policy text for most real
    merchants and scored them near zero, while still carrying 40% of the risk
    weight. Verified against stripe.com: discovery found only `contact` after
    cleaning, versus `contact`, `privacy`, and `terms` on an untouched tree.

    Text nodes are filtered by ancestor instead, which leaves the tree intact.
    """
    parts: list[str] = []
    length = 0

    for node in soup.find_all(string=True):
        # find_all(string=True) also yields Comment, Doctype, CData and
        # ProcessingInstruction — all NavigableString subclasses. Including them
        # floods the extract with build-time markup: amazon.com's policy pages
        # returned 6000 characters of "sp:feature:head-start" CSM instrumentation
        # comments instead of policy prose, which starved the compliance rubric
        # of anything to match. Keep only real text nodes.
        if type(node) is not NavigableString or isinstance(node, Comment):
            continue
        if any(parent.name in _NOISE_TAGS for parent in node.parents):
            continue
        text = node.strip()
        if not text:
            continue
        parts.append(text)
        length += len(text) + 1
        if length >= max_chars:
            break

    return " ".join(parts)[:max_chars]


def _usable_anchors(soup: BeautifulSoup, base_url: str):
    """Yield (anchor, absolute_url, lowercased href) for followable links."""
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor["href"]).strip()
        lowered = raw_href.lower()
        # Skip other protocols, mailto, javascript, pure fragments
        if any(lowered.startswith(p) for p in ("mailto:", "tel:", "javascript:", "#")):
            continue
        full_url = urljoin(base_url, raw_href)
        # urljoin can yield odd schemes; only follow web links.
        if not full_url.lower().startswith(("http://", "https://")):
            continue
        yield anchor, full_url, lowered


def _discover_policy_links(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    """
    Map anchors to our policy keys, matching the URL first and the link text second.

    Two passes, because URL matching alone misses large merchants entirely:
    Amazon publishes its Conditions of Use and Privacy Notice at opaque paths
    like `/gp/help/customer/display.html?nodeId=468496` — the keyword only ever
    appears in the anchor *text*. An href match is stronger evidence than a text
    match, so hrefs win and text only fills the keys still missing.
    """
    found: dict[str, str] = {}
    anchors = list(_usable_anchors(soup, base_url))

    def best_key(haystack: str) -> Optional[str]:
        """
        Pick the policy key whose *longest* keyword matches.

        Longest-match matters because the keyword sets overlap: "/legal/privacy-policy"
        contains both "legal" (terms) and "privacy" (privacy). Taking the first
        key in dict order would file the privacy policy under terms and then let
        a weaker match claim the privacy slot.
        """
        best: Optional[str] = None
        best_len = 0
        for key, keywords in _POLICY_KEYWORD_MAP.items():
            if key in found:
                continue
            for kw in keywords:
                if kw in haystack and len(kw) > best_len:
                    best, best_len = key, len(kw)
        return best

    # Pass 1 — the URL contains the keyword (highest confidence).
    for _anchor, full_url, lowered_href in anchors:
        if len(found) == len(_POLICY_KEYWORD_MAP):
            return found
        key = best_key(lowered_href)
        if key:
            found[key] = full_url

    # Pass 2 — the visible link text names the policy. Capped at 60 characters
    # so a product title ("Privacy Screen Protector, 3-pack") cannot masquerade
    # as a privacy policy link.
    for anchor, full_url, _lowered_href in anchors:
        if len(found) == len(_POLICY_KEYWORD_MAP):
            break
        text = anchor.get_text(strip=True).lower()
        if not text or len(text) > 60:
            continue
        key = best_key(text)
        if key:
            found[key] = full_url

    return found


def _extract_products(soup: BeautifulSoup, limit: int = 20) -> list[ProductItem]:
    """
    Attempt CSS-selector heuristics for common e-commerce frameworks,
    then fall back to heading extraction.
    """
    products: list[ProductItem] = []

    # Ordered list of (title_selector, desc_selector, price_selector) tuples
    selector_sets = [
        (".product-card__title", ".product-card__description", ".product-card__price"),
        (".product-item__title", ".product-item__description", ".product-item__price"),
        (".product-title", ".product-description", ".price"),
        ('[class*="product"] h2', '[class*="product"] p', '[class*="price"]'),
        ("article h2", "article p", "article .price"),
        (".item-title", ".item-description", ".item-price"),
        (".grid__item h3", ".grid__item p", ".grid__item .money"),
    ]

    for title_sel, desc_sel, price_sel in selector_sets:
        titles: list[Tag] = soup.select(title_sel)
        if not titles:
            continue
        descs = soup.select(desc_sel)
        prices = soup.select(price_sel)
        for i, t_tag in enumerate(titles[:limit]):
            title = t_tag.get_text(strip=True)
            if not title:
                continue
            products.append(
                ProductItem(
                    title=title,
                    description=descs[i].get_text(strip=True) if i < len(descs) else "",
                    price=prices[i].get_text(strip=True) if i < len(prices) else "",
                )
            )
        if products:
            return products[:limit]

    # Generic fallback — headings that look like product names
    for heading in soup.select("h1, h2, h3")[:limit]:
        text = heading.get_text(strip=True)
        if 4 < len(text) < 120:
            products.append(ProductItem(title=text))

    return products[:limit]


async def _fetch_page_text(context: BrowserContext, url: str) -> str:
    """
    Navigate to URL in a fresh page tab and return cleaned body text.
    Returns empty string on any error (timeout, 404, JS error, etc.).
    """
    page: Page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=_POLICY_TIMEOUT_MS)
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        return _clean_soup_text(soup, max_chars=6000)
    except PlaywrightTimeoutError:
        logger.debug("Timeout fetching policy page: %s", url)
        return ""
    except Exception as exc:  # noqa: BLE001 — a bad policy page must not fail the scan
        logger.debug("Error fetching %s: %s", url, exc)
        return ""
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


# ─── Public API ───────────────────────────────────────────────────────────────

async def _scrape_merchant_inner(url: str, max_products: int) -> MerchantScrapeResult:
    context: BrowserContext = await BrowserManager.new_context()
    try:
        # ── 1. Homepage ──────────────────────────────────────────────────────
        home_page: Page = await context.new_page()
        status: Optional[int] = None
        try:
            response = await home_page.goto(
                url, wait_until="domcontentloaded", timeout=_HOMEPAGE_TIMEOUT_MS
            )
            status = response.status if response else None
            # Give client-rendered storefronts a moment to paint their footer,
            # which is where policy links almost always live.
            try:
                await home_page.wait_for_load_state("networkidle", timeout=4_000)
            except PlaywrightTimeoutError:
                pass  # Busy pages never go idle; the DOM we have is good enough.
            html = await home_page.content()
        except Exception as exc:  # noqa: BLE001 — reported via .error
            logger.error("Failed to load homepage %s: %s", url, exc)
            return MerchantScrapeResult(
                url=url,
                title="",
                meta_description="",
                homepage_text="",
                policy_texts=PolicyTexts(),
                error=str(exc),
                http_status=status,
            )
        finally:
            try:
                await home_page.close()
            except Exception:  # noqa: BLE001
                pass

        soup = BeautifulSoup(html, "lxml")

        # A WAF challenge is not the merchant's site. Report it as such rather
        # than letting downstream agents read "no policies, no products" off a
        # CAPTCHA page and score the merchant as non-compliant.
        block_reason = _detect_block(status, html, soup)
        if block_reason:
            logger.warning(
                "Scrape of %s was blocked (%s, HTTP %s) — reporting as unverifiable.",
                url,
                block_reason,
                status,
            )
            return MerchantScrapeResult(
                url=url,
                title="",
                meta_description="",
                homepage_text="",
                policy_texts=PolicyTexts(),
                blocked=True,
                block_reason=block_reason,
                http_status=status,
                error=f"Site blocked automated inspection ({block_reason})",
            )

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = (
            str(meta_tag["content"]).strip()
            if meta_tag and meta_tag.get("content")
            else ""
        )
        # Discover links and products from the intact tree first. _clean_soup_text
        # is non-mutating, but keeping discovery ahead of it makes the dependency
        # explicit — footer links must survive to be found.
        policy_links = _discover_policy_links(soup, url)
        products = _extract_products(soup, limit=max_products)
        homepage_text = _clean_soup_text(soup)

        # ── 2. Policy pages (concurrent) ─────────────────────────────────────
        policy_texts = PolicyTexts()
        if policy_links:
            fetch_coros = {
                key: _fetch_page_text(context, link)
                for key, link in policy_links.items()
            }
            results = await asyncio.gather(*fetch_coros.values(), return_exceptions=True)
            for key, result in zip(fetch_coros.keys(), results):
                if isinstance(result, str):
                    setattr(policy_texts, key, result)

        logger.info(
            "Scrape complete for %s — %d products, policy keys: %s",
            url,
            len(products),
            list(policy_links.keys()),
        )
        return MerchantScrapeResult(
            url=url,
            title=title,
            meta_description=meta_desc,
            homepage_text=homepage_text,
            policy_texts=policy_texts,
            products=products,
            http_status=status,
        )
    finally:
        try:
            await context.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ignoring context close error for %s: %s", url, exc)


async def scrape_merchant(url: str, max_products: int = 20) -> MerchantScrapeResult:
    """
    Full merchant scrape:
      1. Scrape homepage — title, meta description, body text, product listings.
      2. Discover policy page links from anchors.
      3. Concurrently fetch all discovered policy pages.

    Never raises — errors are captured in `.error`, and the whole operation is
    bounded by `_SCRAPE_BUDGET_SECONDS`.
    """
    try:
        return await asyncio.wait_for(
            _scrape_merchant_inner(url, max_products), timeout=_SCRAPE_BUDGET_SECONDS
        )
    except asyncio.TimeoutError:
        logger.error("Scrape exceeded %.0fs budget for %s", _SCRAPE_BUDGET_SECONDS, url)
        return MerchantScrapeResult(
            url=url,
            title="",
            meta_description="",
            homepage_text="",
            policy_texts=PolicyTexts(),
            error=f"Scrape timed out after {_SCRAPE_BUDGET_SECONDS:.0f}s",
        )
    except Exception as exc:  # noqa: BLE001 — the pipeline must always get a result
        logger.exception("Unexpected scrape failure for %s", url)
        return MerchantScrapeResult(
            url=url,
            title="",
            meta_description="",
            homepage_text="",
            policy_texts=PolicyTexts(),
            error=str(exc),
        )
