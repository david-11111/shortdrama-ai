"""add security tables: audit_log, token_blacklist, login_attempts

Revision ID: 008_add_security_tables
Revises: 007_add_constraints
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "008_add_security_tables"
down_revision: Union[str, None] = "007_add_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE token_blacklist (
            id BIGSERIAL PRIMARY KEY,
            jti VARCHAR(64) NOT NULL UNIQUE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_token_blacklist_jti ON token_blacklist(jti)")
    op.execute("CREATE INDEX idx_token_blacklist_expires ON token_blacklist(expires_at)")

    op.execute("""
        CREATE TABLE audit_log (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(100) NOT NULL,
            target_type VARCHAR(50),
            target_id VARCHAR(64),
            payload JSONB DEFAULT '{}'::jsonb,
            ip VARCHAR(45),
            user_agent VARCHAR(512),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_audit_log_user_id ON audit_log(user_id)")
    op.execute("CREATE INDEX idx_audit_log_action ON audit_log(action)")
    op.execute("CREATE INDEX idx_audit_log_created_at ON audit_log(created_at)")

    op.execute("""
        CREATE TABLE login_attempts (
            id BIGSERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            ip VARCHAR(45),
            success BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_login_attempts_email ON login_attempts(email)")
    op.execute("CREATE INDEX idx_login_attempts_ip ON login_attempts(ip)")
    op.execute("CREATE INDEX idx_login_attempts_created_at ON login_attempts(created_at)")

    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS hmac_salt VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS hmac_salt;")
    op.execute("DROP TABLE IF EXISTS login_attempts;")
    op.execute("DROP TABLE IF EXISTS audit_log;")
    op.execute("DROP TABLE IF EXISTS token_blacklist;")
