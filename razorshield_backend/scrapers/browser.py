"""
razorshield_backend/scrapers/browser.py
────────────────────────────────────────
Async Playwright-based web scraper for merchant homepages and policy pages.

Design:
  - BrowserManager is a process-wide singleton — one Chromium instance is
    launched on startup and reused across all inspections (prevents memory leaks).
  - Each call to `scrape_merchant` gets its own BrowserContext (separate cookies /
    storage), which is always closed in a finally block.
  - Policy pages are fetched concurrently with asyncio.gather.
  - All navigation failures silently return empty strings — the agents
    downstream treat missing content as low-compliance signals.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
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

    @property
    def scrape_failed(self) -> bool:
        return self.error is not None and not self.homepage_text


# ─── Singleton browser manager ────────────────────────────────────────────────

class BrowserManager:
    """
    Process-level Playwright Chromium singleton.
    Must be initialised once at FastAPI startup and closed at shutdown.
    """
    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def initialize(cls) -> None:
        async with cls._lock:
            if cls._browser is not None:
                return
            cls._playwright = await async_playwright().start()
            cls._browser = await cls._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                ],
            )
            logger.info("Playwright Chromium browser launched successfully.")

    @classmethod
    async def close(cls) -> None:
        async with cls._lock:
            if cls._browser:
                await cls._browser.close()
                cls._browser = None
            if cls._playwright:
                await cls._playwright.stop()
                cls._playwright = None
            logger.info("Playwright browser closed.")

    @classmethod
    async def new_context(cls) -> BrowserContext:
        if cls._browser is None:
            await cls.initialize()
        return await cls._browser.new_context(  # type: ignore[union-attr]
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
            java_script_enabled=True,
        )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _clean_soup_text(soup: BeautifulSoup, max_chars: int = 8000) -> str:
    """Remove chrome & noise tags, return plain text up to max_chars."""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)[:max_chars]


def _discover_policy_links(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    """
    Walk all anchor tags and map them to our policy keys.
    First match per key wins.
    """
    found: dict[str, str] = {}
    base_domain = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(base_url))

    for anchor in soup.find_all("a", href=True):
        if len(found) == len(_POLICY_KEYWORD_MAP):
            break  # all keys found — stop scanning

        raw_href: str = str(anchor["href"]).lower().strip()
        # Skip external domains, mailto, javascript, fragments
        if any(raw_href.startswith(p) for p in ("mailto:", "tel:", "javascript:", "#")):
            continue

        full_url = urljoin(base_url, anchor["href"])

        for key, keywords in _POLICY_KEYWORD_MAP.items():
            if key in found:
                continue
            if any(kw in raw_href for kw in keywords):
                found[key] = full_url
                break

    return found


def _extract_products(soup: BeautifulSoup) -> list[ProductItem]:
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
        for i, t_tag in enumerate(titles[:20]):
            products.append(
                ProductItem(
                    title=t_tag.get_text(strip=True),
                    description=descs[i].get_text(strip=True) if i < len(descs) else "",
                    price=prices[i].get_text(strip=True) if i < len(prices) else "",
                )
            )
        return products[:20]

    # Generic fallback — headings that look like product names
    for heading in soup.select("h1, h2, h3")[:20]:
        text = heading.get_text(strip=True)
        if 4 < len(text) < 120:
            products.append(ProductItem(title=text))

    return products[:20]


async def _fetch_page_text(context: BrowserContext, url: str) -> str:
    """
    Navigate to URL in a fresh page tab and return cleaned body text.
    Returns empty string on any error (timeout, 404, JS error, etc.).
    """
    page: Page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=12_000)
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        return _clean_soup_text(soup, max_chars=6000)
    except PlaywrightTimeoutError:
        logger.debug("Timeout fetching policy page: %s", url)
        return ""
    except Exception as exc:
        logger.debug("Error fetching %s: %s", url, exc)
        return ""
    finally:
        await page.close()


# ─── Public API ───────────────────────────────────────────────────────────────

async def scrape_merchant(url: str) -> MerchantScrapeResult:
    """
    Full merchant scrape:
      1. Scrape homepage — title, meta description, body text, product listings.
      2. Discover policy page links from anchors.
      3. Concurrently fetch all discovered policy pages.
    Returns MerchantScrapeResult. Never raises — errors are captured in .error.
    """
    context: BrowserContext = await BrowserManager.new_context()
    try:
        # ── 1. Homepage ──────────────────────────────────────────────────────
        home_page: Page = await context.new_page()
        try:
            await home_page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            html = await home_page.content()
        except Exception as exc:
            logger.error("Failed to load homepage %s: %s", url, exc)
            return MerchantScrapeResult(
                url=url,
                title="",
                meta_description="",
                homepage_text="",
                policy_texts=PolicyTexts(),
                error=str(exc),
            )
        finally:
            await home_page.close()

        soup = BeautifulSoup(html, "lxml")

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = (
            str(meta_tag["content"]).strip()
            if meta_tag and meta_tag.get("content")
            else ""
        )
        homepage_text = _clean_soup_text(soup)
        policy_links = _discover_policy_links(soup, url)
        products = _extract_products(soup)

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
        )
    finally:
        await context.close()
