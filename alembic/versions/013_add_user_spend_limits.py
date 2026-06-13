"""add user spend limits

Revision ID: 013
Revises: 012
"""

from alembic import op


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_spend_limits (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            daily_credit_limit INTEGER,
            is_unlimited BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_user_spend_limits_daily_limit
                CHECK (daily_credit_limit IS NULL OR daily_credit_limit > 0)
        )
        """
    )
    op.execute("CREATE INDEX idx_user_spend_limits_user_id ON user_spend_limits(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_spend_limits")
