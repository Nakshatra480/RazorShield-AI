"""
razorshield_backend/agents/catalog_agent.py
────────────────────────────────────────────
Prohibited goods detector using local sentence-transformer embeddings
and pgvector cosine similarity search.

Pipeline:
  1. Encode each product title + description using BAAI/bge-base-en-v1.5
     (768-dim, fully local, no API key required).
  2. For each product embedding, execute a pgvector `<=>` cosine distance
     query against the `prohibited_patterns` table.
  3. Items with cosine similarity > threshold are flagged.
  4. Falls back to keyword-matching if the prohibited_patterns table is empty.

The SentenceTransformer model is loaded once at process start (lru_cache)
and reused for all requests.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from razorshield_backend.config import Settings, get_settings
from razorshield_backend.db.database import get_session
from razorshield_backend.scrapers.browser import ProductItem

logger = logging.getLogger(__name__)


# ─── Hardcoded keyword fallback (used when prohibited_patterns table is empty) ─

_PROHIBITED_KEYWORDS: set[str] = {
    # Weapons
    "gun", "firearm", "pistol", "rifle", "ammo", "ammunition", "silencer",
    "switchblade", "brass knuckles", "taser",
    # Drugs / pharmaceuticals
    "opioid", "fentanyl", "methamphetamine", "cocaine", "heroin", "mdma",
    "prescription drug", "controlled substance", "research chemical",
    # Counterfeit
    "replica watch", "fake designer", "counterfeit", "knockoff", "imitation brand",
    # Gambling
    "casino chip", "poker chip", "slot machine hack", "bet credits",
    # Exploitation
    "darkweb", "hacked account", "stolen data", "identity theft kit",
}


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


# ─── Agent ────────────────────────────────────────────────────────────────────

class CatalogAgent:
    """
    Stateless catalog safety agent.
    Instantiate once and reuse across requests.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    def _get_model(self) -> SentenceTransformer:
        return _load_embedding_model(self._settings.embedding_model_name)

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """Return a (N, 768) float32 numpy array of normalised embeddings."""
        model = self._get_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,    # cosine sim = dot product after L2 norm
            show_progress_bar=False,
            batch_size=16,
        )
        return np.array(embeddings, dtype=np.float32)

    def _keyword_fallback(self, products: list[ProductItem]) -> list[FlaggedItem]:
        """
        Simple keyword scan used when the prohibited_patterns table is empty.
        Not as accurate as vector search but provides a safety net.
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

    async def _vector_search(
        self, embedding: np.ndarray, threshold: float
    ) -> list[dict]:
        """
        Cosine similarity search against prohibited_patterns using pgvector.
        `<=>` is the cosine distance operator; similarity = 1 - distance.
        """
        # Format as PostgreSQL vector literal
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding.tolist()) + "]"
        query = text(
            """
            SELECT
                category,
                pattern_text,
                1 - (embedding <=> :vec::vector) AS similarity
            FROM prohibited_patterns
            WHERE 1 - (embedding <=> :vec::vector) > :threshold
            ORDER BY similarity DESC
            LIMIT 3
            """
        )
        async with get_session() as session:
            result = await session.execute(
                query, {"vec": vec_literal, "threshold": threshold}
            )
            return [
                {
                    "category": row.category,
                    "pattern_text": row.pattern_text,
                    "similarity": float(row.similarity),
                }
                for row in result.fetchall()
            ]

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

        try:
            pattern_count = await self._count_prohibited_patterns()
        except Exception as exc:
            logger.error("Failed to count prohibited patterns: %s", exc)
            pattern_count = 0

        # ── Keyword fallback ─────────────────────────────────────────────────
        if pattern_count == 0:
            logger.warning(
                "prohibited_patterns table is empty — using keyword fallback. "
                "Run benchmark.py to seed the table."
            )
            flagged = self._keyword_fallback(products)
            catalog_score = max(0.0, 1.0 - len(flagged) * 0.15)
            return CatalogResult(
                has_prohibited_items=bool(flagged),
                catalog_score=catalog_score,
                flagged_items=flagged,
                checked_via_vectors=False,
            )

        # ── Vector search ────────────────────────────────────────────────────
        product_texts = [
            f"{p.title} {p.description}".strip() for p in products
        ]

        try:
            # Encode all products in one batch (run in thread to not block event loop)
            embeddings: np.ndarray = await asyncio.to_thread(
                self._embed_texts, product_texts
            )
        except Exception as exc:
            logger.error("Embedding generation failed: %s", exc)
            # Fall back to keyword matching
            flagged = self._keyword_fallback(products)
            return CatalogResult(
                has_prohibited_items=bool(flagged),
                catalog_score=max(0.0, 1.0 - len(flagged) * 0.15),
                flagged_items=flagged,
                checked_via_vectors=False,
                agent_error=str(exc),
            )

        threshold = self._settings.prohibited_similarity_threshold
        flagged: list[FlaggedItem] = []

        # Query vector DB for each product embedding concurrently
        search_tasks = [
            self._vector_search(embeddings[i], threshold)
            for i in range(len(products))
        ]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        for i, result in enumerate(search_results):
            if isinstance(result, Exception):
                logger.warning("Vector search error for product %d: %s", i, result)
                continue
            for match in result:
                flagged.append(
                    FlaggedItem(
                        product_title=products[i].title,
                        matched_category=match["category"],
                        matched_pattern=match["pattern_text"],
                        similarity_score=match["similarity"],
                    )
                )
                break  # one flag per product is sufficient

        # Deduplicate by product title
        seen: set[str] = set()
        unique_flagged: list[FlaggedItem] = []
        for item in flagged:
            if item.product_title not in seen:
                seen.add(item.product_title)
                unique_flagged.append(item)

        # Score: starts at 1.0, reduced by 0.15 per unique flagged item
        catalog_score = max(0.0, 1.0 - len(unique_flagged) * 0.15)

        logger.info(
            "Catalog check: %d products checked, %d flagged (vector search)",
            len(products),
            len(unique_flagged),
        )

        return CatalogResult(
            has_prohibited_items=bool(unique_flagged),
            catalog_score=catalog_score,
            flagged_items=unique_flagged,
        )
