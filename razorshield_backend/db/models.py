"""
razorshield_backend/db/models.py
─────────────────────────────────
SQLAlchemy ORM models for RazorShield AI.

Tables:
  merchants          — tracked merchant domains
  scans              — inspection results linked to a merchant
  prohibited_patterns — pgvector catalogue of forbidden goods embeddings
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from razorshield_backend.db.database import Base


# ─── Enumerations ─────────────────────────────────────────────────────────────

class RiskTier(str, enum.Enum):
    """Three-tier risk classification produced by the orchestrator."""
    SAFE = "SAFE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    HIGH_RISK = "HIGH_RISK"


# ─── Merchants ────────────────────────────────────────────────────────────────

class Merchant(Base):
    """
    Represents a unique merchant domain submitted for inspection.
    Multiple scans can be associated with the same merchant.
    """
    __tablename__ = "merchants"
    __table_args__ = (
        UniqueConstraint("domain_url", name="uq_merchants_domain_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain_url: Mapped[str] = mapped_column(
        String(512), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # one merchant → many scans
    scans: Mapped[list["Scan"]] = relationship(
        "Scan",
        back_populates="merchant",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Merchant id={self.id} url={self.domain_url!r}>"


# ─── Scans ────────────────────────────────────────────────────────────────────

class Scan(Base):
    """
    Stores the complete output of one multi-agent inspection run.

    findings_json: structured per-agent results (domain info, policy result,
                   catalog result, guardrail info, weighted breakdown).
    audit_trail:   human-readable LLM-generated narrative explaining the verdict.
    """
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    overall_risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(
        SAEnum(RiskTier, name="risk_tier_enum", create_type=True), nullable=False
    )
    findings_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    audit_trail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="scans")

    def __repr__(self) -> str:
        return (
            f"<Scan id={self.id} tier={self.risk_tier} score={self.overall_risk_score:.1f}>"
        )


# ─── Prohibited Patterns ──────────────────────────────────────────────────────

class ProhibitedPattern(Base):
    """
    Seed catalogue of known prohibited or high-risk product types.

    embedding: 768-dimensional BGE-base vector representation of `pattern_text`,
               used for cosine similarity matching against merchant catalog items.
    """
    __tablename__ = "prohibited_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    pattern_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Vector(768) matches BAAI/bge-base-en-v1.5 output dimension
    embedding: Mapped[list] = mapped_column(Vector(768), nullable=False)

    def __repr__(self) -> str:
        return f"<ProhibitedPattern category={self.category!r} text={self.pattern_text[:40]!r}>"
