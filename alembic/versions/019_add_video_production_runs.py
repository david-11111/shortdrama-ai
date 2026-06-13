"""add video production runs

Revision ID: 019
Revises: 018
Create Date: 2026-05-19
"""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS video_production_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agent_run_id UUID NULL REFERENCES agent_runs(id) ON DELETE SET NULL,
            episode INTEGER NOT NULL DEFAULT 1,
            scene INTEGER NOT NULL DEFAULT 1,
            target_duration_sec INTEGER NOT NULL DEFAULT 15,
            status TEXT NOT NULL DEFAULT 'created',
            current_stage TEXT NOT NULL DEFAULT 'created',
            goal TEXT NOT NULL DEFAULT '',
            plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            quality_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            edit_strategy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            final_delivery_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            final_task_id UUID NULL,
            final_video_url TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_video_production_runs_project_user_created "
        "ON video_production_runs(project_id, user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_video_production_runs_agent_run "
        "ON video_production_runs(agent_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_video_production_runs_agent_run")
    op.execute("DROP INDEX IF EXISTS idx_video_production_runs_project_user_created")
    op.execute("DROP TABLE IF EXISTS video_production_runs")
