"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-05-11 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            unique=True,
        ),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("tier", sa.String(length=20), nullable=False, server_default="free"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'["all"]\'::jsonb'),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "credit_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_spent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("tx_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "credit_pricing",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("operation", sa.String(length=50), nullable=False, unique=True),
        sa.Column("credits_cost", sa.Integer(), nullable=False),
        sa.Column(
            "tier_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
    )

    op.execute(
        """
        INSERT INTO credit_pricing (operation, credits_cost) VALUES
            ('video_gen_5s', 10),
            ('video_gen_8s', 15),
            ('video_gen_10s', 20),
            ('image_gen', 2),
            ('llm_refine', 1),
            ('llm_director_chat', 1),
            ('pipeline_analysis', 5)
        """
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            unique=True,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="5"),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("stage_text", sa.String(length=200), nullable=True),
        sa.Column("credits_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_tasks_user_status", "tasks", ["user_id", "status"], unique=False)
    op.create_index(
        "idx_tasks_status_priority",
        "tasks",
        ["status", "priority", "created_at"],
        unique=False,
    )

    op.create_table(
        "dead_letter_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("original_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "error_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "dead_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )

    op.create_table(
        "ark_api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key_name", sa.String(length=50), nullable=False, unique=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="ark"),
        sa.Column(
            "services",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'["seedance","seedream","doubao"]\'::jsonb'),
        ),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("current_load", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rpm_limit", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "rate_limit_config",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("resource", sa.String(length=50), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("max_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tier", "resource", name="uq_rate_limit_config_tier_resource"),
    )

    op.execute(
        """
        INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count) VALUES
            ('free', 'concurrent_tasks', 1, 2),
            ('free', 'video_gen', 3600, 5),
            ('free', 'image_gen', 3600, 20),
            ('pro', 'concurrent_tasks', 1, 10),
            ('pro', 'video_gen', 3600, 50),
            ('pro', 'image_gen', 3600, 200),
            ('enterprise', 'concurrent_tasks', 1, 50),
            ('enterprise', 'video_gen', 3600, 200),
            ('enterprise', 'image_gen', 3600, 1000)
        """
    )


def downgrade() -> None:
    op.drop_table("rate_limit_config")
    op.drop_table("ark_api_keys")
    op.drop_table("dead_letter_tasks")
    op.drop_index("idx_tasks_status_priority", table_name="tasks")
    op.drop_index("idx_tasks_user_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("credit_pricing")
    op.drop_table("credit_transactions")
    op.drop_table("credit_accounts")
    op.drop_table("api_keys")
    op.drop_table("users")
