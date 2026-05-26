"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-25 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_pricing_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("prompt_usd_per_mtok", sa.Float(), nullable=False),
        sa.Column("completion_usd_per_mtok", sa.Float(), nullable=False),
        sa.Column("request_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("image_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("context_length", sa.BigInteger(), nullable=True),
        sa.Column("max_completion_tokens", sa.BigInteger(), nullable=True),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("model_id", "captured_at", name="uq_model_captured"),
    )
    op.create_index(
        "ix_model_pricing_snapshot_captured_at",
        "model_pricing_snapshot",
        ["captured_at"],
    )
    op.create_index(
        "ix_model_pricing_model_id_captured",
        "model_pricing_snapshot",
        ["model_id", "captured_at"],
    )

    op.create_table(
        "kilo_plan_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tier", sa.String(length=64), nullable=False),
        sa.Column("monthly_usd", sa.Float(), nullable=False),
        sa.Column("paid_credits_usd", sa.Float(), nullable=False),
        sa.Column("max_bonus_pct", sa.Float(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_kilo_plan_snapshot_captured_at",
        "kilo_plan_snapshot",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_kilo_plan_snapshot_captured_at", table_name="kilo_plan_snapshot")
    op.drop_table("kilo_plan_snapshot")
    op.drop_index("ix_model_pricing_model_id_captured", table_name="model_pricing_snapshot")
    op.drop_index(
        "ix_model_pricing_snapshot_captured_at", table_name="model_pricing_snapshot"
    )
    op.drop_table("model_pricing_snapshot")
