"""add volcengine billing rows

Revision ID: 011_add_volc_billing_rows
Revises: 010_add_provider_cost_ledger
Create Date: 2026-05-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "011_add_volc_billing_rows"
down_revision: Union[str, None] = "010_add_provider_cost_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE volc_billing_rows (
            id BIGSERIAL PRIMARY KEY,
            transaction_no TEXT NOT NULL UNIQUE,
            account_id TEXT,
            account_name TEXT,
            customer_name TEXT,
            vendor_name TEXT,
            trade_time TIMESTAMPTZ,
            trade_type TEXT,
            channel TEXT,
            channel_transaction_no TEXT,
            business_order_no TEXT,
            amount_yuan NUMERIC(14, 6) NOT NULL,
            cash_balance_yuan NUMERIC(14, 6),
            frozen_amount_yuan NUMERIC(14, 6),
            remark TEXT,
            raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
            match_status VARCHAR(30) NOT NULL DEFAULT 'unmatched',
            provider_usage_cost_id BIGINT REFERENCES provider_usage_costs(id) ON DELETE SET NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_volc_billing_time ON volc_billing_rows(trade_time DESC)")
    op.execute("CREATE INDEX idx_volc_billing_order ON volc_billing_rows(business_order_no)")
    op.execute("CREATE INDEX idx_volc_billing_match ON volc_billing_rows(match_status, trade_time DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS volc_billing_rows")
