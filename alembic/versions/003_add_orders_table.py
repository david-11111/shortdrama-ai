"""add orders table

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002_add_admin_field"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            order_no VARCHAR(64) UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount_cents INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            payment_method VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            trade_no VARCHAR(128),
            paid_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_orders_user_id ON orders(user_id)")
    op.execute("CREATE INDEX idx_orders_order_no ON orders(order_no)")
    op.execute("CREATE INDEX idx_orders_status ON orders(status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS orders;")
