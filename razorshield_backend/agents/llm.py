"""
razorshield_backend/agents/llm.py
──────────────────────────────────
Shared LLM transport for every agent.

Why this module exists
──────────────────────
The agents previously each called ``litellm.acompletion`` directly with a blind
"retry 3 times on any Exception" loop and no timeout. That produced two real
production failures:

  1. A non-retryable error (401 bad key, 402 out of credits, 404 unknown model)
     was retried 3× with 1s + 2s of back-off. With two LLM call sites per scan
     that is ~6 wasted seconds and 6 doomed HTTP requests *per merchant* — the
     50-merchant benchmark spent minutes doing nothing but failing.
  2. No request timeout, so a stalled provider connection hung the whole
     inspection (and the HTTP request behind it) indefinitely.

This module classifies failures and only retries the ones that can actually
succeed on a second attempt, and it reports *why* the LLM is unavailable so
callers can degrade deliberately instead of silently scoring everything 0.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import litellm

from razorshield_backend.config import Settings

logger = logging.getLogger(__name__)

# Drop provider-unsupported params rather than erroring.
litellm.drop_params = True
# LiteLLM's own retry/telemetry layers duplicate ours; keep the transport thin.
litellm.suppress_debug_info = True


class LLMUnavailable(RuntimeError):
    """Raised when the LLM cannot serve a request and retrying will not help."""

    def __init__(
        self,
        reason: str,
        *,
        retryable: bool,
        status_code: Optional[int] = None,
        key_specific: bool = False,
    ):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code
        # True when the failure is a property of the *credential* (out of
        # credits, revoked, account-level quota) rather than the request. Only
        # these are worth retrying on a different key — re-sending a malformed
        # request or an unknown model slug under every key just multiplies the
        # same failure.
        self.key_specific = key_specific


@dataclass(frozen=True)
class LLMHealth:
    """Cached view of whether the provider is currently answering."""
    available: bool
    detail: str
    checked_at: float


# Status codes that will never succeed on retry with the same request/key.
_FATAL_STATUS = {400, 401, 402, 403, 404, 422}
# Status codes worth retrying — transient capacity or upstream faults.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# Fatal because of the credential — a different key may well succeed.
_KEY_FATAL_STATUS = {401, 402, 403}
_KEY_FATAL_MARKERS = (
    "insufficient credits",
    "invalid api key",
    "no auth credentials",
    "authentication",
    "unauthorized",
    "quota exceeded",
    "credit balance",
    "payment required",
)

# Fatal because of the request itself — every key would fail identically.
_REQUEST_FATAL_MARKERS = (
    "not a valid model",
    "does not exist",
    "is not a valid",
)


def _extract_status(exc: BaseException) -> Optional[int]:
    """Pull an HTTP status code off a LiteLLM/provider exception."""
    for attr in ("status_code", "code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
        if isinstance(value, str) and value.isdigit() and 100 <= int(value) <= 599:
            return int(value)

    # Fall back to scraping the rendered message, e.g. '"code":402'
    match = re.search(r'"code"\s*:\s*(\d{3})', str(exc))
    if match:
        return int(match.group(1))
    match = re.search(r"\b(4\d{2}|5\d{2})\b", str(exc))
    return int(match.group(1)) if match else None


def classify_error(exc: BaseException) -> LLMUnavailable:
    """Turn a provider exception into a decision about whether to retry."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return LLMUnavailable("LLM request timed out", retryable=True)

    message = str(exc)
    lowered = message.lower()
    status = _extract_status(exc)

    # Request-level faults first: these are not the credential's fault, so they
    # must not burn through the fallback keys.
    if any(marker in lowered for marker in _REQUEST_FATAL_MARKERS):
        return LLMUnavailable(message[:160], retryable=False, status_code=status)

    if any(marker in lowered for marker in _KEY_FATAL_MARKERS):
        # Trim the provider's verbose JSON blob down to something loggable.
        detail = "Insufficient credits" if "insufficient credits" in lowered else message[:160]
        return LLMUnavailable(
            detail, retryable=False, status_code=status, key_specific=True
        )

    if status in _KEY_FATAL_STATUS:
        return LLMUnavailable(
            f"HTTP {status}: {message[:160]}",
            retryable=False,
            status_code=status,
            key_specific=True,
        )

    if status in _FATAL_STATUS:
        return LLMUnavailable(f"HTTP {status}: {message[:160]}", retryable=False, status_code=status)

    if status in _RETRYABLE_STATUS:
        return LLMUnavailable(f"HTTP {status}: {message[:160]}", retryable=True, status_code=status)

    # Unknown failures (DNS, connection reset, ...) are worth one more attempt.
    return LLMUnavailable(message[:160] or exc.__class__.__name__, retryable=True, status_code=status)


def redact_key(key: str) -> str:
    """Render an API key for logs: never emit more than a short prefix/suffix."""
    if not key:
        return "<unset>"
    return f"{key[:10]}…{key[-4:]}" if len(key) > 18 else "<short-key>"


class LLMClient:
    """
    Thin async wrapper over litellm with timeout, bounded retries, credential
    failover, and a short-lived "provider is down" circuit breaker.

    The breaker matters for the benchmark and for batch traffic: once every key
    is known to be exhausted, the remaining 49 merchants should not each
    re-discover that with their own doomed HTTP calls.

    Failover
    ────────
    `settings.openrouter_api_keys` is the primary key followed by any configured
    fallbacks. When a key is rejected for a *key-specific* reason (out of
    credits, revoked, account quota) the client marks that key exhausted and
    retries the same request on the next one. The working key is remembered, so
    subsequent calls start there rather than re-failing on a dead credential.
    Request-level faults (bad model slug, malformed request) never rotate — they
    would fail identically on every key.
    """

    # How long a known-fatal provider state is trusted before we re-probe.
    _BREAKER_TTL_SECONDS = 60.0
    # Exhausted keys are retried after this long: credits can be topped up.
    _KEY_RETRY_AFTER_SECONDS = 300.0

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._keys: list[str] = settings.openrouter_api_keys
        if not self._keys:
            raise ValueError("No OpenRouter API key configured (OPENROUTER_API_KEY).")
        self._active_index = 0
        # index -> (reason, exhausted_at monotonic)
        self._exhausted: dict[int, tuple[str, float]] = {}
        self._breaker: Optional[LLMHealth] = None
        self._lock = asyncio.Lock()

    # ── Key state ────────────────────────────────────────────────────────────

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def active_key_index(self) -> int:
        return self._active_index

    def key_status(self) -> list[dict[str, Any]]:
        """Per-key state for the readiness probe. Never returns key material."""
        now = time.monotonic()
        report: list[dict[str, Any]] = []
        for i, key in enumerate(self._keys):
            exhausted = self._exhausted.get(i)
            report.append({
                "index": i,
                "label": "primary" if i == 0 else f"fallback-{i}",
                "key": redact_key(key),
                "active": i == self._active_index,
                "status": "exhausted" if exhausted else "available",
                "detail": exhausted[0] if exhausted else None,
                "retry_in_seconds": (
                    max(0, round(self._KEY_RETRY_AFTER_SECONDS - (now - exhausted[1])))
                    if exhausted else None
                ),
            })
        return report

    def _is_exhausted(self, index: int) -> bool:
        entry = self._exhausted.get(index)
        if entry is None:
            return False
        if (time.monotonic() - entry[1]) > self._KEY_RETRY_AFTER_SECONDS:
            # Cooldown elapsed — the account may have been topped up.
            self._exhausted.pop(index, None)
            return False
        return True

    def _mark_exhausted(self, index: int, reason: str) -> None:
        self._exhausted[index] = (reason, time.monotonic())

    def _usable_indices(self) -> list[str]:
        """Key indices to try, active one first, skipping exhausted keys."""
        order = list(range(self._active_index, len(self._keys))) + list(
            range(0, self._active_index)
        )
        return [i for i in order if not self._is_exhausted(i)]

    # ── Breaker state ────────────────────────────────────────────────────────

    @property
    def health(self) -> Optional[LLMHealth]:
        """Last known provider state, or None if never exercised."""
        return self._breaker

    def _breaker_open(self) -> Optional[str]:
        state = self._breaker
        if state is None or state.available:
            return None
        if (time.monotonic() - state.checked_at) > self._BREAKER_TTL_SECONDS:
            return None  # TTL elapsed — allow a probe request through
        return state.detail

    def _record(self, *, available: bool, detail: str) -> None:
        self._breaker = LLMHealth(
            available=available, detail=detail, checked_at=time.monotonic()
        )

    # ── Completion ───────────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        """
        Run a chat completion and return the assistant text.

        Tries the active credential, then each remaining non-exhausted key in
        turn when the failure is key-specific. Raises LLMUnavailable only once
        every key has been ruled out. Callers are expected to degrade gracefully
        rather than propagate a 500.
        """
        tripped = self._breaker_open()
        if tripped:
            raise LLMUnavailable(f"LLM unavailable ({tripped})", retryable=False)

        base_kwargs: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_base": self._settings.openrouter_base_url,
            "timeout": self._settings.llm_timeout_seconds,
        }
        if json_mode:
            base_kwargs["response_format"] = {"type": "json_object"}

        attempts = self._settings.llm_max_attempts
        candidates = self._usable_indices()

        if not candidates:
            # Every key is inside its cooldown window.
            reason = "; ".join(
                f"{'primary' if i == 0 else f'fallback-{i}'}: {r}"
                for i, (r, _) in sorted(self._exhausted.items())
            )
            detail = f"all {len(self._keys)} API key(s) exhausted ({reason})"
            self._record(available=False, detail=detail)
            raise LLMUnavailable(detail, retryable=False, key_specific=True)

        last: Optional[LLMUnavailable] = None

        for key_index in candidates:
            key = self._keys[key_index]
            label = "primary" if key_index == 0 else f"fallback-{key_index}"
            kwargs = {**base_kwargs, "api_key": key}

            for attempt in range(1, attempts + 1):
                try:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**kwargs),
                        timeout=self._settings.llm_timeout_seconds,
                    )
                    content = (response.choices[0].message.content or "").strip()
                    if not content:
                        raise ValueError("Provider returned an empty completion")

                    if key_index != self._active_index:
                        logger.info(
                            "LLM failover succeeded — now using %s key (%s).",
                            label,
                            redact_key(key),
                        )
                        self._active_index = key_index
                    self._record(available=True, detail="ok")
                    return content

                except Exception as exc:  # noqa: BLE001 — classified below
                    last = classify_error(exc)

                    if last.key_specific:
                        # This credential is spent; remember it and move on to
                        # the next key rather than burning the retry budget.
                        logger.warning(
                            "LLM %s key (%s) rejected: %s — trying next key.",
                            label,
                            redact_key(key),
                            last.reason,
                        )
                        self._mark_exhausted(key_index, last.reason)
                        break  # next candidate key

                    if not last.retryable:
                        # Request-level fault: every key fails identically.
                        logger.error(
                            "LLM call failed permanently (%s). Disabling LLM for %.0fs.",
                            last.reason,
                            self._BREAKER_TTL_SECONDS,
                        )
                        self._record(available=False, detail=last.reason)
                        raise last

                    logger.warning(
                        "LLM attempt %d/%d on %s key failed (retryable): %s",
                        attempt,
                        attempts,
                        label,
                        last.reason,
                    )
                    if attempt < attempts:
                        await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s …

        assert last is not None
        exhausted_count = len([i for i in candidates if i in self._exhausted])
        detail = (
            f"{last.reason} (exhausted {exhausted_count}/{len(self._keys)} API keys)"
            if exhausted_count
            else last.reason
        )
        self._record(available=False, detail=detail)
        raise LLMUnavailable(
            detail,
            retryable=False,
            status_code=last.status_code,
            key_specific=last.key_specific,
        )

    async def probe(self) -> LLMHealth:
        """
        Cheap readiness check used by GET /api/v1/readiness.
        Reuses cached state when it is fresh to avoid burning quota on polling.
        """
        async with self._lock:
            state = self._breaker
            if state and (time.monotonic() - state.checked_at) < self._BREAKER_TTL_SECONDS:
                return state

            try:
                await self.complete(
                    system_prompt="Reply with the single word: ok",
                    user_message="ping",
                    max_tokens=5,
                )
                return self._breaker or LLMHealth(True, "ok", time.monotonic())
            except LLMUnavailable as exc:
                self._record(available=False, detail=exc.reason)
                return self._breaker  # type: ignore[return-value]
