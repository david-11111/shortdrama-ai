"""add final edit plans

Revision ID: 014
Revises: 013
"""

from alembic import op


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE final_edit_plans (
            id BIGSERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (project_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_final_edit_plans_project ON final_edit_plans(project_id)")
    op.execute("CREATE INDEX idx_final_edit_plans_user ON final_edit_plans(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS final_edit_plans")
