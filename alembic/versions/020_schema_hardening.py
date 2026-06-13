"""schema hardening for production data integrity

Revision ID: 020_schema_hardening
Revises: 019
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "020_schema_hardening"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


FOREIGN_KEY_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    (
        "assets",
        "fk_assets_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "assets",
        "fk_assets_user",
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "agent_runs",
        "fk_agent_runs_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "agent_events",
        "fk_agent_events_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "agent_artifacts",
        "fk_agent_artifacts_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "agent_interrupts",
        "fk_agent_interrupts_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE NOT VALID",
    ),
    (
        "video_production_runs",
        "fk_video_production_runs_final_task",
        "FOREIGN KEY (final_task_id) REFERENCES tasks(task_id) ON DELETE SET NULL NOT VALID",
    ),
    (
        "provider_usage_costs",
        "fk_provider_usage_costs_project",
        "FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL NOT VALID",
    ),
)

CHECK_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    (
        "tasks",
        "chk_tasks_progress_range",
        "CHECK (progress >= 0 AND progress <= 100) NOT VALID",
    ),
    (
        "agent_events",
        "chk_agent_events_progress_range",
        "CHECK (progress IS NULL OR (progress >= 0 AND progress <= 100)) NOT VALID",
    ),
    (
        "agent_runs",
        "chk_agent_runs_credit_counters_non_negative",
        """
        CHECK (
            estimated_max_credits >= 0
            AND allowed_max_credits >= 0
            AND reserved_credits >= 0
            AND spent_credits >= 0
            AND remaining_run_budget >= 0
        ) NOT VALID
        """,
    ),
    (
        "video_production_runs",
        "chk_video_production_runs_positive_targets",
        "CHECK (episode >= 1 AND scene >= 1 AND target_duration_sec >= 1) NOT VALID",
    ),
)

DUPLICATE_INDEXES: tuple[str, ...] = (
    "idx_orders_order_no",
    "idx_user_spend_limits_user_id",
)


def _assert_identifier(value: str) -> str:
    if not value or not all(char in _IDENTIFIER_CHARS for char in value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


def _add_constraint_if_missing(table: str, name: str, ddl: str) -> None:
    table = _assert_identifier(table)
    name = _assert_identifier(name)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
                  AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name} {ddl};
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # Drop indexes that duplicate existing UNIQUE constraints.
    for index_name in DUPLICATE_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {_assert_identifier(index_name)}")

    # Foreign keys are added NOT VALID to avoid scanning existing production rows
    # during deploy. PostgreSQL still checks new/updated rows after creation.
    for table, name, ddl in FOREIGN_KEY_CONSTRAINTS:
        _add_constraint_if_missing(table, name, ddl)

    # Low-risk value guards for fields updated by the main task/agent paths.
    for table, name, ddl in CHECK_CONSTRAINTS:
        _add_constraint_if_missing(table, name, ddl)

    # Document the known storage tradeoff without changing the application path.
    op.execute(
        """
        COMMENT ON TABLE final_video_blobs IS
        'Fallback storage for final videos. Prefer external/object storage for large commercial workloads.';
        """
    )


def downgrade() -> None:
    for table, name, _ddl in reversed(CHECK_CONSTRAINTS + FOREIGN_KEY_CONSTRAINTS):
        op.execute(
            f"ALTER TABLE {_assert_identifier(table)} "
            f"DROP CONSTRAINT IF EXISTS {_assert_identifier(name)}"
        )
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_spend_limits_user_id ON user_spend_limits(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_no ON orders(order_no)")
