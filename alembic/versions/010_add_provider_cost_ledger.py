"""add provider cost ledger

Revision ID: 010_add_provider_cost_ledger
Revises: 009_add_media_tables
Create Date: 2026-05-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "010_add_provider_cost_ledger"
down_revision: Union[str, None] = "009_add_media_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_pricing_rules (
            id BIGSERIAL PRIMARY KEY,
            provider VARCHAR(50) NOT NULL,
            service VARCHAR(50) NOT NULL,
            model VARCHAR(100) NOT NULL DEFAULT '*',
            billing_basis VARCHAR(50) NOT NULL,
            unit_prices JSONB NOT NULL DEFAULT '{}'::jsonb,
            currency VARCHAR(10) NOT NULL DEFAULT 'CNY',
            source TEXT,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            effective_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_provider_pricing_lookup ON provider_pricing_rules(provider, service, model, active)"
    )

    op.execute(
        """
        CREATE TABLE provider_usage_costs (
            id BIGSERIAL PRIMARY KEY,
            task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            project_id VARCHAR(32),
            provider VARCHAR(50) NOT NULL,
            service VARCHAR(50) NOT NULL,
            model VARCHAR(100) NOT NULL,
            billing_basis VARCHAR(50) NOT NULL,
            provider_task_id TEXT,
            provider_order_no TEXT,
            local_call_id UUID NOT NULL DEFAULT gen_random_uuid(),
            input_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            total_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            raw_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            unit_prices JSONB NOT NULL DEFAULT '{}'::jsonb,
            estimated_cost_yuan NUMERIC(14, 6),
            actual_cost_yuan NUMERIC(14, 6),
            actual_billing_order_no TEXT,
            match_status VARCHAR(30) NOT NULL DEFAULT 'unmatched',
            credits_charged INTEGER,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_provider_usage_task ON provider_usage_costs(task_id)")
    op.execute("CREATE INDEX idx_provider_usage_user_time ON provider_usage_costs(user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_provider_usage_service_time ON provider_usage_costs(service, created_at DESC)")
    op.execute("CREATE INDEX idx_provider_usage_match ON provider_usage_costs(match_status, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS provider_usage_costs")
    op.execute("DROP TABLE IF EXISTS provider_pricing_rules")
