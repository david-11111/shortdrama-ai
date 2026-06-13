"""add agent table index optimizations

Revision ID: 018
Revises: 017
Create Date: 2026-05-19
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_events: (run_id, created_at DESC) — 补 DESC 方向，原有 ASC 版本保留
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_events_run_created_desc "
        "ON agent_events(run_id, created_at DESC)"
    )

    # agent_runs: (project_id, user_id, created_at DESC) 复合索引
    # 原有 idx_agent_runs_project_created 只含 project_id，不含 user_id
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_project_user_created "
        "ON agent_runs(project_id, user_id, started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_runs_project_user_created")
    op.execute("DROP INDEX IF EXISTS idx_agent_events_run_created_desc")
