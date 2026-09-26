"""drop redundant (model_id, captured_at) index

The uq_model_captured unique constraint already creates a btree on
(model_id, captured_at); ix_model_pricing_model_id_captured duplicated it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_model_pricing_model_id_captured", table_name="model_pricing_snapshot")


def downgrade() -> None:
    op.create_index(
        "ix_model_pricing_model_id_captured",
        "model_pricing_snapshot",
        ["model_id", "captured_at"],
    )
