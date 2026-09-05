"""
razorshield_backend/config.py
─────────────────────────────
Central settings loaded from .env via Pydantic BaseSettings.
Cached with @lru_cache so the .env file is parsed exactly once.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to the project root (one level above this package)
_ENV_FILE: Path = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    """All runtime configuration for RazorShield AI backend."""

    # ── LLM / OpenRouter ──────────────────────────────────────────────────────
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Free-tier Llama 3.1 70B via OpenRouter — no credit card needed
    llm_model: str = "meta-llama/llama-3.1-70b-instruct:free"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str  # Neon PostgreSQL connection string

    # ── Local Embeddings (sentence-transformers, no API key needed) ───────────
    # 768-dimensional, BGE-base is fast, accurate, and fully free
    embedding_model_name: str = "BAAI/bge-base-en-v1.5"

    # ── Concurrency ───────────────────────────────────────────────────────────
    # Max simultaneous merchant inspections (respects OpenRouter rate limits)
    max_concurrent_inspections: int = 5

    # ── Similarity threshold for prohibited catalog items ─────────────────────
    # Cosine similarity > this threshold → item is flagged
    prohibited_similarity_threshold: float = 0.75

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
