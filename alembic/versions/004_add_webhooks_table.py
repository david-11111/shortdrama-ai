"""add webhooks table

Revision ID: 004
Revises: 003
"""
from alembic import op

revision = "004_add_webhooks_table"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE webhooks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            url VARCHAR(512) NOT NULL,
            events VARCHAR(256) NOT NULL DEFAULT 'task.complete,task.failed',
            secret VARCHAR(128) DEFAULT '',
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_webhooks_user_id ON webhooks(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhooks;")
