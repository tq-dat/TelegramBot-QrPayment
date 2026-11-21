"""Migration 004: unique index on orders.transaction_id.

One bank transaction may pay at most one order (check_payments job).

Revision ID: 004
Revises: 003
Create Date: 2026-11-21
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_orders_transaction_id", "orders", ["transaction_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_orders_transaction_id", table_name="orders")
