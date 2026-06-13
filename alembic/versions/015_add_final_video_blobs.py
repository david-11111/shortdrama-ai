"""add final video blobs fallback

Revision ID: 015
Revises: 014
"""

from alembic import op


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE final_video_blobs (
            task_id UUID PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content_type TEXT NOT NULL DEFAULT 'video/mp4',
            file_size BIGINT NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_final_video_blobs_project ON final_video_blobs(project_id)")
    op.execute("CREATE INDEX idx_final_video_blobs_user ON final_video_blobs(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS final_video_blobs")
