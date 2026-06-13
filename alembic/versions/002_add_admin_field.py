"""add is_admin field to users

Revision ID: 002_add_admin_field
Revises: 001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "002_add_admin_field"
down_revision = "001_initial_schema"


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))


def downgrade() -> None:
    op.drop_column("users", "is_admin")
