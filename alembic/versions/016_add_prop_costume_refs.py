"""add prop and costume refs to shot rows

Revision ID: 016
Revises: 015
"""

from alembic import op


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE shot_rows ADD COLUMN IF NOT EXISTS prop_refs_json JSONB NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE shot_rows ADD COLUMN IF NOT EXISTS costume_refs_json JSONB NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE shot_rows DROP COLUMN IF EXISTS costume_refs_json")
    op.execute("ALTER TABLE shot_rows DROP COLUMN IF EXISTS prop_refs_json")
