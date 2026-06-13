"""add workbench tables

Revision ID: 005_add_workbench_tables
Revises: 004_add_webhooks_table
Create Date: 2026-05-12 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "005_add_workbench_tables"
down_revision: Union[str, None] = "004_add_webhooks_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE projects (
            id BIGSERIAL PRIMARY KEY,
            project_id VARCHAR(32) NOT NULL UNIQUE,
            user_id BIGINT NOT NULL REFERENCES users(id),
            name VARCHAR(255),
            input_path TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            progress REAL NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_projects_user ON projects(user_id)")
    op.execute("CREATE INDEX idx_projects_project_id ON projects(project_id)")

    op.execute(
        """
        CREATE TABLE shot_rows (
            id BIGSERIAL PRIMARY KEY,
            project_id VARCHAR(32) NOT NULL,
            user_id BIGINT NOT NULL,
            shot_index INTEGER NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            duration REAL NOT NULL DEFAULT 5.0,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            selected BOOLEAN NOT NULL DEFAULT FALSE,
            character_refs_json JSONB NOT NULL DEFAULT '[]',
            scene_refs_json JSONB NOT NULL DEFAULT '[]',
            style_refs_json JSONB NOT NULL DEFAULT '[]',
            image_candidates_json JSONB NOT NULL DEFAULT '[]',
            selected_image TEXT,
            video_variants_json JSONB NOT NULL DEFAULT '[]',
            selected_video TEXT,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(project_id, shot_index)
        )
        """
    )
    op.execute("CREATE INDEX idx_shot_rows_project ON shot_rows(project_id)")
    op.execute("CREATE INDEX idx_shot_rows_user ON shot_rows(user_id)")

    op.execute(
        """
        CREATE TABLE assets (
            id BIGSERIAL PRIMARY KEY,
            asset_id VARCHAR(32) NOT NULL UNIQUE,
            project_id VARCHAR(32) NOT NULL,
            user_id BIGINT NOT NULL,
            asset_type VARCHAR(30) NOT NULL DEFAULT 'image',
            file_path TEXT,
            file_url TEXT,
            metadata_json JSONB,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_assets_project ON assets(project_id)")
    op.execute("CREATE INDEX idx_assets_user ON assets(user_id)")
    op.execute("CREATE INDEX idx_assets_type ON assets(asset_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assets")
    op.execute("DROP TABLE IF EXISTS shot_rows")
    op.execute("DROP TABLE IF EXISTS projects")