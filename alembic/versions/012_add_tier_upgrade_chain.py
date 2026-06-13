"""add tier upgrade fields for payment chain

Revision ID: 012
Revises: 011_add_volc_billing_rows
"""

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011_add_volc_billing_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tier_expires_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "orders",
        sa.Column("order_type", sa.String(length=30), nullable=False, server_default="topup"),
    )
    op.add_column("orders", sa.Column("plan_id", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("tier_target", sa.String(length=20), nullable=True))
    op.add_column(
        "orders",
        sa.Column("tier_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_orders_order_type", "orders", ["order_type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_orders_order_type", table_name="orders")
    op.drop_column("orders", "tier_days")
    op.drop_column("orders", "tier_target")
    op.drop_column("orders", "plan_id")
    op.drop_column("orders", "order_type")
    op.drop_column("users", "tier_expires_at")
