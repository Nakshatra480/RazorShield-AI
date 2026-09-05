"""
razorshield_backend/config.py
─────────────────────────────
Central settings loaded from .env via Pydantic BaseSettings.
Cached with @lru_cache so the .env file is parsed exactly once.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to the project root (one level above this package)
_ENV_FILE: Path = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    """All runtime configuration for RazorShield AI backend."""

    # ── LLM / OpenRouter ──────────────────────────────────────────────────────
    openrouter_api_key: str
    # Optional standby key(s), tried in order when the primary is rejected for a
    # key-specific reason (out of credits, revoked, rate-limited at account
    # level). Comma-separate to supply more than one.
    openrouter_fallback_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Free-tier Llama 3.1 70B via OpenRouter — use standard slug (no :free suffix)
    llm_model: str = "openrouter/meta-llama/llama-3.1-70b-instruct"

    # Hard ceiling on a single LLM round-trip. Without this a hung provider
    # connection blocks the inspection request indefinitely.
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    # Attempts per LLM call, including the first. Only *retryable* failures
    # (timeouts, 429, 5xx) consume an attempt — see agents/llm.py.
    llm_max_attempts: int = Field(default=3, ge=1, le=6)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str  # Neon PostgreSQL connection string
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)

    # ── Local Embeddings (sentence-transformers, no API key needed) ───────────
    # 768-dimensional, BGE-base is fast, accurate, and fully free
    embedding_model_name: str = "BAAI/bge-base-en-v1.5"
    # Must match the Vector(...) dimension on ProhibitedPattern.embedding.
    embedding_dimensions: int = Field(default=768, gt=0)

    # ── Concurrency ───────────────────────────────────────────────────────────
    # Max simultaneous merchant inspections. Enforced by a global semaphore in
    # main.py so bursts of traffic cannot exhaust the DB pool or the LLM quota.
    max_concurrent_inspections: int = Field(default=5, ge=1, le=100)

    # Ceiling on products embedded + vector-searched per scan. Product
    # extraction falls back to page headings, which can yield a lot of noise.
    max_products_per_scan: int = Field(default=20, ge=1, le=200)

    # Whole-pipeline budget for one inspection (scrape + agents + narrative).
    inspection_timeout_seconds: float = Field(default=180.0, gt=0)

    # ── Similarity threshold for prohibited catalog items ─────────────────────
    # Cosine similarity > this threshold → item is flagged
    prohibited_similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated exact origins allowed to call the API.
    cors_allow_origins: str = "http://localhost:3000,http://localhost:3001"
    # Regex for dynamic origins (preview deployments). Starlette matches
    # `allow_origins` by exact string only, so wildcards MUST go here.
    cors_allow_origin_regex: str = r"https://.*\.vercel\.app"

    # ── Environment ───────────────────────────────────────────────────────────
    # In "production" the API stops echoing internal exception text to clients.
    environment: str = "development"

    @field_validator("environment")
    @classmethod
    def _normalise_environment(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def openrouter_api_keys(self) -> list[str]:
        """
        Primary key first, then any configured fallbacks, de-duplicated while
        preserving order. LLMClient walks this list when a key is rejected for a
        key-specific reason so a single exhausted account cannot disable the LLM.
        """
        raw = [self.openrouter_api_key, *self.openrouter_fallback_api_key.split(",")]
        keys: list[str] = []
        for key in raw:
            cleaned = key.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
        return keys

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton. Call this everywhere."""
    return Settings()
