"""add media_files, frames, transcripts, reports tables

Revision ID: 009_add_media_tables
Revises: 008_add_security_tables
Create Date: 2026-05-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "009_add_media_tables"
down_revision: Union[str, None] = "008_add_security_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TABLE media_files (id BIGSERIAL PRIMARY KEY, project_id VARCHAR(32) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, file_name TEXT NOT NULL, file_path TEXT NOT NULL, file_size BIGINT NOT NULL DEFAULT 0, duration_sec REAL NOT NULL DEFAULT 0, width INTEGER, height INTEGER, fps REAL, video_codec TEXT, audio_codec TEXT, bitrate BIGINT NOT NULL DEFAULT 0, has_audio BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
    op.execute("CREATE INDEX idx_media_files_project ON media_files(project_id)")
    op.execute("CREATE INDEX idx_media_files_user ON media_files(user_id)")

    op.execute("CREATE TABLE scenes (id BIGSERIAL PRIMARY KEY, project_id VARCHAR(32) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, media_file_id BIGINT NOT NULL REFERENCES media_files(id) ON DELETE CASCADE, scene_index INTEGER NOT NULL, start_sec REAL NOT NULL DEFAULT 0, end_sec REAL NOT NULL DEFAULT 0, preview_image_path TEXT, status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(media_file_id, scene_index))")
    op.execute("CREATE INDEX idx_scenes_project ON scenes(project_id)")
    op.execute("CREATE INDEX idx_scenes_media_file ON scenes(media_file_id)")

    op.execute("CREATE TABLE frames (id BIGSERIAL PRIMARY KEY, project_id VARCHAR(32) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, media_file_id BIGINT NOT NULL REFERENCES media_files(id) ON DELETE CASCADE, scene_id BIGINT REFERENCES scenes(id) ON DELETE SET NULL, frame_index INTEGER NOT NULL, timestamp_sec REAL NOT NULL, image_path TEXT, brightness REAL, sharpness REAL, motion_score REAL)")
    op.execute("CREATE INDEX idx_frames_media_file ON frames(media_file_id)")
    op.execute("CREATE INDEX idx_frames_scene ON frames(scene_id)")

    op.execute("CREATE TABLE transcripts (id BIGSERIAL PRIMARY KEY, project_id VARCHAR(32) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, media_file_id BIGINT NOT NULL REFERENCES media_files(id) ON DELETE CASCADE, scene_id BIGINT REFERENCES scenes(id) ON DELETE SET NULL, speaker TEXT, start_sec REAL NOT NULL DEFAULT 0, end_sec REAL NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '', confidence REAL)")
    op.execute("CREATE INDEX idx_transcripts_media_file ON transcripts(media_file_id)")

    op.execute("CREATE TABLE reports (id BIGSERIAL PRIMARY KEY, project_id VARCHAR(32) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, report_type VARCHAR(50) NOT NULL, content_json JSONB NOT NULL DEFAULT '{}', content_markdown TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
    op.execute("CREATE INDEX idx_reports_project ON reports(project_id)")
    op.execute("CREATE INDEX idx_reports_type ON reports(project_id, report_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reports")
    op.execute("DROP TABLE IF EXISTS transcripts")
    op.execute("DROP TABLE IF EXISTS frames")
    op.execute("DROP TABLE IF EXISTS scenes")
    op.execute("DROP TABLE IF EXISTS media_files")
