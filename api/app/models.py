"""SQLAlchemy ORM models for historical pricing."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModelPricingSnapshot(Base):
    """One row per (model, captured_at). Append-only — drives trends."""

    __tablename__ = "model_pricing_snapshot"
    __table_args__ = (
        UniqueConstraint("model_id", "captured_at", name="uq_model_captured"),
        Index("ix_model_pricing_model_id_captured", "model_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Prices in USD per 1M tokens (we normalize from OpenRouter's per-token).
    prompt_usd_per_mtok: Mapped[float] = mapped_column(Float, nullable=False)
    completion_usd_per_mtok: Mapped[float] = mapped_column(Float, nullable=False)
    request_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    image_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")

    context_length: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_completion_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    supports_tools: Mapped[bool] = mapped_column(default=False)
    supports_vision: Mapped[bool] = mapped_column(default=False)

    raw: Mapped[str] = mapped_column(Text, nullable=False)  # source JSON, debugging

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class KiloPlanSnapshot(Base):
    """Snapshot of Kilo Pass tier definitions — change detection."""

    __tablename__ = "kilo_plan_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(String(64), nullable=False)
    monthly_usd: Mapped[float] = mapped_column(Float, nullable=False)
    paid_credits_usd: Mapped[float] = mapped_column(Float, nullable=False)
    max_bonus_pct: Mapped[float] = mapped_column(Float, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
