"""task credit transaction integrity

Revision ID: 021_task_credit_tx_integrity
Revises: 020_schema_hardening
Create Date: 2026-05-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "021_task_credit_tx_integrity"
down_revision: Union[str, None] = "020_schema_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("credit_transaction_id", sa.String(length=64), nullable=True))
    op.execute(
        """
        UPDATE tasks
        SET credit_transaction_id = payload->>'_credit_transaction_id'
        WHERE credit_transaction_id IS NULL
          AND payload ? '_credit_transaction_id'
        """
    )
    op.create_index(
        "idx_tasks_credit_transaction_id",
        "tasks",
        ["credit_transaction_id"],
        unique=False,
    )
    op.create_index(
        "uq_credit_transactions_reference_type",
        "credit_transactions",
        ["reference_id", "tx_type"],
        unique=True,
        postgresql_where=sa.text("reference_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_transactions_reference_type", table_name="credit_transactions")
    op.drop_index("idx_tasks_credit_transaction_id", table_name="tasks")
    op.drop_column("tasks", "credit_transaction_id")
