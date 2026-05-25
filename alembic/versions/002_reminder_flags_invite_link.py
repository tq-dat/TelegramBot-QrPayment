"""Migration 002: Add reminder flags to subscriptions, invite_link to orders.

Revision ID: 002
Revises: 001
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("d3_reminder_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("d1_reminder_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "orders",
        sa.Column("invite_link", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "d3_reminder_sent")
    op.drop_column("subscriptions", "d1_reminder_sent")
    op.drop_column("orders", "invite_link")
