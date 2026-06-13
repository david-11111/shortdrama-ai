"""add final video asset references

Revision ID: 022_add_final_video_assets
Revises: 021_task_credit_tx_integrity
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "022_add_final_video_assets"
down_revision: Union[str, None] = "021_task_credit_tx_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS final_video_assets (
            task_id UUID PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            storage_mode VARCHAR(24) NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'video/mp4',
            file_size BIGINT NOT NULL,
            file_path TEXT,
            file_url TEXT,
            oss_key TEXT,
            checksum_sha256 VARCHAR(64),
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_final_video_assets_storage
                CHECK (storage_mode IN ('oss', 'local_file', 'db_blob')),
            CONSTRAINT chk_final_video_assets_location
                CHECK (
                    (storage_mode = 'oss' AND file_url IS NOT NULL AND file_url <> '')
                    OR (storage_mode = 'local_file' AND file_path IS NOT NULL AND file_path <> '')
                    OR storage_mode = 'db_blob'
                ),
            CONSTRAINT chk_final_video_assets_file_size
                CHECK (file_size >= 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_final_video_assets_project ON final_video_assets(project_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_final_video_assets_user ON final_video_assets(user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_final_video_assets_storage ON final_video_assets(storage_mode)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_final_video_assets_storage")
    op.execute("DROP INDEX IF EXISTS idx_final_video_assets_user")
    op.execute("DROP INDEX IF EXISTS idx_final_video_assets_project")
    op.execute("DROP TABLE IF EXISTS final_video_assets")
