"""
razorshield_backend/agents/catalog_agent.py
────────────────────────────────────────────
Prohibited goods detector using local sentence-transformer embeddings
and pgvector cosine similarity search.

Pipeline:
  1. Encode each product title + description using BAAI/bge-base-en-v1.5
     (768-dim, fully local, no API key required).
  2. Run ONE batched pgvector query that finds the nearest prohibited pattern
     for every product at once.
  3. Items whose cosine similarity exceeds the threshold are flagged.
  4. Falls back to keyword matching if the prohibited_patterns table is empty
     or the embedding model cannot be loaded.

The SentenceTransformer model is loaded once per process (lru_cache) and reused.
"""

import asyncio
import logging
import math
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from razorshield_backend.config import Settings, get_settings
from razorshield_backend.db.database import get_session
from razorshield_backend.scrapers.browser import ProductItem

# PyTorch/sentence-transformers is NOT thread-safe for concurrent encode() calls.
# This lock ensures only one thread encodes at a time — prevents SIGSEGV under load.
_EMBED_LOCK = threading.Lock()

logger = logging.getLogger(__name__)


# ─── Hardcoded keyword fallback (used when prohibited_patterns table is empty) ─
# Ordered (not a set) so the matched keyword for a given product is deterministic
# — a risk verdict must not vary between runs on identical input.
_PROHIBITED_KEYWORDS: tuple[str, ...] = (
    # Weapons
    "ammunition", "brass knuckles", "firearm", "silencer", "switchblade",
    "taser", "pistol", "rifle", "ammo", "gun",
    # Drugs / pharmaceuticals
    "controlled substance", "prescription drug", "research chemical",
    "methamphetamine", "fentanyl", "cocaine", "heroin", "opioid", "mdma",
    # Counterfeit
    "counterfeit", "fake designer", "imitation brand", "replica watch", "knockoff",
    # Gambling
    "slot machine hack", "bet credits", "casino chip", "poker chip",
    # Exploitation
    "identity theft kit", "hacked account", "stolen data", "darkweb",
)


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class FlaggedItem:
    """A product that matched a prohibited pattern."""
    product_title: str
    matched_category: str
    matched_pattern: str
    similarity_score: float


@dataclass
class CatalogResult:
    """Output from the Catalog Safety Agent."""
    has_prohibited_items: bool
    catalog_score: float                        # 1.0 = clean, 0.0 = fully prohibited
    flagged_items: list[FlaggedItem] = field(default_factory=list)
    checked_via_vectors: bool = True            # False = keyword fallback was used
    agent_error: Optional[str] = None


# ─── Model singleton ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_embedding_model(model_name: str) -> SentenceTransformer:
    """
    Load the sentence-transformer model exactly once per process.
    First call downloads the model (~400 MB) to HuggingFace cache.
    """
    logger.info("Loading embedding model: %s", model_name)
    model = SentenceTransformer(model_name)
    logger.info("Embedding model loaded (%d-dim).", model.get_sentence_embedding_dimension())
    return model


def to_vector_literal(embedding) -> str:
    """
    Render an embedding as a PostgreSQL vector literal, e.g. '[0.1,0.2,...]'.

    The values are interpolated into SQL rather than bound, because asyncpg
    cannot cast a bound Python string to the pgvector type ($1::vector raises
    PostgresSyntaxError). Every element is therefore validated to be a finite
    float and re-rendered with a fixed format, so nothing but digits, '-', '.'
    and ',' can reach the statement — a non-numeric value raises instead of
    being concatenated into SQL.
    """
    values = []
    for raw in embedding:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"Embedding contains a non-finite value: {raw!r}")
        values.append(f"{value:.6f}")
    if not values:
        raise ValueError("Refusing to build an empty vector literal")
    return "[" + ",".join(values) + "]"


# ─── Agent ────────────────────────────────────────────────────────────────────

class CatalogAgent:
    """
    Stateless catalog safety agent.
    Instantiate once and reuse across requests.
    """

    # Each flagged product costs this much catalog score.
    _PENALTY_PER_ITEM = 0.15

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    def _get_model(self) -> SentenceTransformer:
        return _load_embedding_model(self._settings.embedding_model_name)

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """
        Return a (N, dim) float32 numpy array of normalised embeddings.
        Serialised through _EMBED_LOCK to prevent concurrent PyTorch calls
        which cause segmentation faults under asyncio.to_thread concurrency.
        """
        model = self._get_model()
        with _EMBED_LOCK:
            embeddings = model.encode(
                texts,
                normalize_embeddings=True,    # cosine sim = dot product after L2 norm
                show_progress_bar=False,
                batch_size=16,
            )
        return np.array(embeddings, dtype=np.float32)

    def _keyword_fallback(self, products: list[ProductItem]) -> list[FlaggedItem]:
        """
        Simple keyword scan used when vector search is unavailable.
        Less accurate than vector search but provides a safety net.
        """
        flagged: list[FlaggedItem] = []
        for product in products:
            combined = f"{product.title} {product.description}".lower()
            for kw in _PROHIBITED_KEYWORDS:
                if kw in combined:
                    flagged.append(
                        FlaggedItem(
                            product_title=product.title,
                            matched_category="keyword-match",
                            matched_pattern=kw,
                            similarity_score=1.0,
                        )
                    )
                    break
        return flagged

    def _fallback_result(
        self, products: list[ProductItem], error: Optional[str] = None
    ) -> CatalogResult:
        flagged = self._keyword_fallback(products)
        return CatalogResult(
            has_prohibited_items=bool(flagged),
            catalog_score=self._score_for(len(flagged)),
            flagged_items=flagged,
            checked_via_vectors=False,
            agent_error=error,
        )

    def _score_for(self, flagged_count: int) -> float:
        return round(max(0.0, 1.0 - flagged_count * self._PENALTY_PER_ITEM), 4)

    async def _batch_vector_search(
        self, embeddings: np.ndarray, threshold: float
    ) -> dict[int, dict]:
        """
        Find the nearest prohibited pattern for every product in ONE round trip.

        The previous implementation opened a separate `get_session()` — and
        therefore a separate pooled connection — for each product, then ran them
        all concurrently via asyncio.gather. With up to 20 products per scan and
        a pool of 5 (+10 overflow), a single scan could saturate the pool and
        concurrent scans would block on connection checkout. One batched query
        on one connection removes that failure mode entirely.
        """
        probes = ",\n                ".join(
            f"({i}, '{to_vector_literal(embeddings[i])}'::vector)"
            for i in range(len(embeddings))
        )

        query = text(
            f"""
            WITH probes (idx, embedding) AS (
                VALUES
                {probes}
            )
            SELECT
                p.idx                                          AS idx,
                m.category                                     AS category,
                m.pattern_text                                 AS pattern_text,
                1 - (m.embedding <=> p.embedding)              AS similarity
            FROM probes p
            CROSS JOIN LATERAL (
                SELECT category, pattern_text, embedding
                FROM prohibited_patterns
                ORDER BY embedding <=> p.embedding
                LIMIT 1
            ) m
            WHERE 1 - (m.embedding <=> p.embedding) > :threshold
            """
        )

        async with get_session() as session:
            result = await session.execute(query, {"threshold": threshold})
            return {
                int(row.idx): {
                    "category": row.category,
                    "pattern_text": row.pattern_text,
                    "similarity": float(row.similarity),
                }
                for row in result.fetchall()
            }

    async def _count_prohibited_patterns(self) -> int:
        """Check if the prohibited_patterns table has been seeded."""
        async with get_session() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM prohibited_patterns"))
            return int(result.scalar() or 0)

    async def evaluate(self, products: list[ProductItem]) -> CatalogResult:
        """
        Check all products against the prohibited patterns catalogue.

        Returns a CatalogResult with:
          - catalog_score: 1.0 if all clean, decreasing per flagged item
          - flagged_items: list of matched products with category + similarity
        """
        if not products:
            return CatalogResult(
                has_prohibited_items=False,
                catalog_score=1.0,
                flagged_items=[],
            )

        # Bound the work a single scan can do — heading-based product extraction
        # can otherwise hand us a page's entire outline to embed.
        limit = self._settings.max_products_per_scan
        if len(products) > limit:
            logger.info("Truncating catalog from %d to %d products.", len(products), limit)
            products = products[:limit]

        try:
            pattern_count = await self._count_prohibited_patterns()
        except Exception as exc:  # noqa: BLE001 — degrade to keywords, never fail the scan
            logger.error("Failed to count prohibited patterns: %s", exc)
            return self._fallback_result(products, error=f"Pattern table unreachable: {exc}")

        if pattern_count == 0:
            logger.warning(
                "prohibited_patterns table is empty — using keyword fallback. "
                "Seed it with: python3.11 -m razorshield_backend.benchmark"
            )
            return self._fallback_result(products)

        product_texts = [f"{p.title} {p.description}".strip() for p in products]

        try:
            embeddings: np.ndarray = await asyncio.to_thread(self._embed_texts, product_texts)
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding generation failed: %s", exc)
            return self._fallback_result(products, error=str(exc))

        expected_dim = self._settings.embedding_dimensions
        if embeddings.ndim != 2 or embeddings.shape[1] != expected_dim:
            # A dimension mismatch would make every pgvector comparison error out.
            logger.error(
                "Embedding dimension mismatch: model produced %s, schema expects %d.",
                embeddings.shape,
                expected_dim,
            )
            return self._fallback_result(
                products,
                error=f"Embedding dim {embeddings.shape} != expected {expected_dim}",
            )

        threshold = self._settings.prohibited_similarity_threshold

        try:
            matches = await self._batch_vector_search(embeddings, threshold)
        except Exception as exc:  # noqa: BLE001
            logger.error("Vector search failed: %s", exc)
            return self._fallback_result(products, error=str(exc))

        flagged: list[FlaggedItem] = []
        seen_titles: set[str] = set()
        for idx in sorted(matches):
            if idx >= len(products):
                continue
            title = products[idx].title
            if title in seen_titles:
                continue
            seen_titles.add(title)
            match = matches[idx]
            flagged.append(
                FlaggedItem(
                    product_title=title,
                    matched_category=match["category"],
                    matched_pattern=match["pattern_text"],
                    similarity_score=match["similarity"],
                )
            )

        logger.info(
            "Catalog check: %d products checked, %d flagged (vector search)",
            len(products),
            len(flagged),
        )

        return CatalogResult(
            has_prohibited_items=bool(flagged),
            catalog_score=self._score_for(len(flagged)),
            flagged_items=flagged,
        )
