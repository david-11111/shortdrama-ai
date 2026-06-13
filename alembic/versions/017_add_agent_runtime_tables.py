"""add agent runtime tables

Revision ID: 017
Revises: 016
"""

from alembic import op


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id VARCHAR(64) NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            trigger_type VARCHAR(40) NOT NULL DEFAULT 'user_click',
            mode VARCHAR(24) NOT NULL DEFAULT 'step',
            goal TEXT NOT NULL DEFAULT '',
            status VARCHAR(24) NOT NULL DEFAULT 'running',
            current_phase VARCHAR(80) NOT NULL DEFAULT '',
            estimated_max_credits INTEGER NOT NULL DEFAULT 0,
            allowed_max_credits INTEGER NOT NULL DEFAULT 0,
            reserved_credits INTEGER NOT NULL DEFAULT 0,
            spent_credits INTEGER NOT NULL DEFAULT 0,
            remaining_run_budget INTEGER NOT NULL DEFAULT 0,
            production_ledger JSONB NOT NULL DEFAULT '{}',
            summary TEXT NOT NULL DEFAULT '',
            final_decision TEXT NOT NULL DEFAULT '',
            meta JSONB NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_project_created ON agent_runs(project_id, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created ON agent_runs(user_id, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
            step_index INTEGER NOT NULL,
            phase VARCHAR(80) NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            input_summary TEXT NOT NULL DEFAULT '',
            decision_summary TEXT NOT NULL DEFAULT '',
            output_summary TEXT NOT NULL DEFAULT '',
            stop_reason TEXT NOT NULL DEFAULT '',
            meta JSONB NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(run_id, step_index)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps(run_id, step_index)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NULL REFERENCES agent_runs(id) ON DELETE SET NULL,
            project_id VARCHAR(64) NOT NULL,
            task_id UUID NULL,
            step_id UUID NULL REFERENCES agent_steps(id) ON DELETE SET NULL,
            user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            source VARCHAR(40) NOT NULL,
            event_type VARCHAR(40) NOT NULL DEFAULT 'log',
            phase VARCHAR(80) NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            status VARCHAR(24) NOT NULL DEFAULT 'running',
            progress SMALLINT NULL,
            meta JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_project_created ON agent_events(project_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_run_created ON agent_events(run_id, created_at ASC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events(task_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_artifacts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NULL REFERENCES agent_runs(id) ON DELETE SET NULL,
            project_id VARCHAR(64) NOT NULL,
            task_id UUID NULL,
            user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            artifact_type VARCHAR(40) NOT NULL,
            uri TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            meta JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_artifacts_run ON agent_artifacts(run_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_artifacts_project ON agent_artifacts(project_id, created_at DESC)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_interrupts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
            project_id VARCHAR(64) NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            interrupt_type VARCHAR(40) NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_interrupts_run ON agent_interrupts(run_id, created_at DESC)")

    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS run_id UUID NULL REFERENCES agent_runs(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_run_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS run_id")
    op.execute("DROP TABLE IF EXISTS agent_interrupts")
    op.execute("DROP TABLE IF EXISTS agent_artifacts")
    op.execute("DROP TABLE IF EXISTS agent_events")
    op.execute("DROP TABLE IF EXISTS agent_steps")
    op.execute("DROP TABLE IF EXISTS agent_runs")
