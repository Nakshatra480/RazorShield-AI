"""
razorshield_backend/scrapers/whois_client.py
──────────────────────────────────────────────
Domain intelligence inspector: registration age, SSL validity, and registrar.

Uses:
  - tldextract  : robust root domain extraction (handles subdomains, ccTLDs)
  - python-whois: WHOIS registry queries with creation date parsing
  - ssl + socket : TLS certificate inspection without external dependencies

All functions are synchronous (WHOIS and SSL are blocking I/O) and are
wrapped in asyncio.to_thread for use in the async orchestrator.
"""

import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import tldextract
import whois

logger = logging.getLogger(__name__)


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class DomainInspection:
    """Structured result of a domain footprint check."""
    domain: str
    domain_age_days: int         # -1 = unknown / WHOIS failed
    is_ssl_valid: bool
    ssl_expiry_days: int         # -1 = SSL invalid or could not inspect
    registrar: str
    registration_date: Optional[str]  # ISO-8601 string or None


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _get_root_domain(url: str) -> str:
    """Extract the registrable root domain from any URL."""
    ext = tldextract.extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    # Fallback: strip scheme/path manually
    clean = url.replace("https://", "").replace("http://", "").split("/")[0]
    return clean.split(":")[0]  # strip port


def _query_whois(domain: str) -> tuple[int, str, Optional[str]]:
    """
    Query WHOIS for domain age and registrar.
    Returns (domain_age_days, registrar, registration_date_iso).
    On any failure returns (-1, '', None).
    """
    try:
        w = whois.whois(domain)
        creation = w.creation_date

        # python-whois may return a list when multiple records exist
        if isinstance(creation, list):
            creation = creation[0]

        if not isinstance(creation, datetime):
            return -1, str(w.registrar or ""), None

        # Normalise to UTC-aware datetime for comparison
        if creation.tzinfo is None:
            creation = creation.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age_days = (now - creation).days

        registrar = str(w.registrar or "Unknown")
        reg_date_iso = creation.strftime("%Y-%m-%dT%H:%M:%SZ")

        return max(age_days, 0), registrar, reg_date_iso

    except Exception as exc:
        logger.warning("WHOIS query failed for %s: %s", domain, exc)
        return -1, "", None


def _check_ssl(domain: str, port: int = 443) -> tuple[bool, int]:
    """
    Attempt a TLS handshake and inspect the certificate expiry.
    Returns (is_valid, days_until_expiry).
    Returns (False, -1) on connection failure, expired cert, or invalid hostname.
    """
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as tls_sock:
                cert = tls_sock.getpeercert()
                if not cert:
                    return False, -1

                not_after_str = cert.get("notAfter", "")
                if not not_after_str:
                    return False, -1

                expiry = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                expiry = expiry.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_remaining = (expiry - now).days

                return days_remaining > 0, days_remaining

    except ssl.SSLCertVerificationError:
        logger.debug("SSL cert verification failed for %s", domain)
        return False, -1
    except ssl.SSLError as exc:
        logger.debug("SSL error for %s: %s", domain, exc)
        return False, -1
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.debug("Connection error checking SSL for %s: %s", domain, exc)
        return False, -1


# ─── Public API ───────────────────────────────────────────────────────────────

def inspect_domain_sync(url: str) -> DomainInspection:
    """
    Synchronous domain inspection (WHOIS + SSL).
    Call this via asyncio.to_thread in async contexts.
    """
    domain = _get_root_domain(url)
    age_days, registrar, reg_date = _query_whois(domain)
    is_ssl_valid, ssl_expiry_days = _check_ssl(domain)

    logger.info(
        "Domain inspection complete: %s — age=%d days, ssl=%s, expiry=%d days",
        domain,
        age_days,
        is_ssl_valid,
        ssl_expiry_days,
    )

    return DomainInspection(
        domain=domain,
        domain_age_days=age_days,
        is_ssl_valid=is_ssl_valid,
        ssl_expiry_days=ssl_expiry_days,
        registrar=registrar,
        registration_date=reg_date,
    )


async def inspect_domain(url: str) -> DomainInspection:
    """
    Async wrapper for domain inspection.
    Runs blocking WHOIS + socket code in a thread pool.
    """
    import asyncio
    return await asyncio.to_thread(inspect_domain_sync, url)
