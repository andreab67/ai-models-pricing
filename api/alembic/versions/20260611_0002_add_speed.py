"""add throughput/latency speed columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_pricing_snapshot",
        sa.Column("throughput_tps", sa.Float(), nullable=True),
    )
    op.add_column(
        "model_pricing_snapshot",
        sa.Column("latency_ms", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_pricing_snapshot", "latency_ms")
    op.drop_column("model_pricing_snapshot", "throughput_tps")
