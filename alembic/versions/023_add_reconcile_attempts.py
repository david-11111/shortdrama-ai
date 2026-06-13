"""add reconcile_attempts column to tasks table

Revision ID: 023_add_reconcile_attempts
Revises: 022_add_final_video_assets
Create Date: 2026-06-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_add_reconcile_attempts"
down_revision: Union[str, None] = "022_add_final_video_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "reconcile_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "reconcile_attempts")
