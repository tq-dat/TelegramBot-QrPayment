"""Plans table

Revision ID: 003
Revises: 002
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("emoji", sa.String(8), nullable=False, server_default="🎫"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_plans_code", "plans", ["code"], unique=True)

    # Seed the 4 default plans
    op.execute("""
        INSERT INTO plans (code, name, days, price, emoji, sort_order, is_visible) VALUES
        ('basic',    'Basic',    30,  2000,     '⭐', 1, true),
        ('standard', 'Standard', 60,  900000,   '🔥', 2, true),
        ('premium',  'Premium',  90,  1200000,  '💎', 3, true),
        ('ultimate', 'Ultimate', 365, 4200000,  '👑', 4, true)
    """)


def downgrade() -> None:
    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")
