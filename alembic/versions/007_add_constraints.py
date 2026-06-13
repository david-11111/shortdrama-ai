"""add constraints to credit_accounts and shot_rows

Revision ID: 007_add_constraints
Revises: 006_add_rate_limit_resources
Create Date: 2026-05-12 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "007_add_constraints"
down_revision: Union[str, None] = "006_add_rate_limit_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # credit_accounts.balance must never go negative
    op.execute(
        "ALTER TABLE credit_accounts ADD CONSTRAINT chk_balance_non_negative CHECK (balance >= 0)"
    )

    # shot_rows: shot_index must be non-negative, duration must be positive
    op.execute(
        "ALTER TABLE shot_rows ADD CONSTRAINT chk_shot_index_non_negative CHECK (shot_index >= 0)"
    )
    op.execute(
        "ALTER TABLE shot_rows ADD CONSTRAINT chk_shot_duration_positive CHECK (duration > 0)"
    )

    # shot_rows.project_id → projects.project_id foreign key
    op.execute(
        """
        ALTER TABLE shot_rows
        ADD CONSTRAINT fk_shot_rows_project
        FOREIGN KEY (project_id) REFERENCES projects(project_id)
        ON DELETE CASCADE
        """
    )

    # shot_rows.user_id → users.id foreign key (was missing in 005)
    op.execute(
        """
        ALTER TABLE shot_rows
        ADD CONSTRAINT fk_shot_rows_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE shot_rows DROP CONSTRAINT IF EXISTS fk_shot_rows_user")
    op.execute("ALTER TABLE shot_rows DROP CONSTRAINT IF EXISTS fk_shot_rows_project")
    op.execute("ALTER TABLE shot_rows DROP CONSTRAINT IF EXISTS chk_shot_duration_positive")
    op.execute("ALTER TABLE shot_rows DROP CONSTRAINT IF EXISTS chk_shot_index_non_negative")
    op.execute(
        "ALTER TABLE credit_accounts DROP CONSTRAINT IF EXISTS chk_balance_non_negative"
    )
