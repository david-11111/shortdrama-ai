"""add rate_limit_config resources for tts/director/llm

Revision ID: 006_add_rate_limit_resources
Revises: 005_add_workbench_tables
Create Date: 2026-05-12 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "006_add_rate_limit_resources"
down_revision: Union[str, None] = "005_add_workbench_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count) VALUES
            ('free',       'tts_gen',              3600,  10),
            ('pro',        'tts_gen',              3600, 100),
            ('enterprise', 'tts_gen',              3600, 500),

            ('free',       'director_script',      3600,   5),
            ('pro',        'director_script',      3600,  50),
            ('enterprise', 'director_script',      3600, 200),

            ('free',       'director_produce',     3600,   3),
            ('pro',        'director_produce',     3600,  30),
            ('enterprise', 'director_produce',     3600, 100),

            ('free',       'director_ref_images',  3600,   5),
            ('pro',        'director_ref_images',  3600,  50),
            ('enterprise', 'director_ref_images',  3600, 200),

            ('free',       'llm_chat',             3600,  20),
            ('pro',        'llm_chat',             3600, 200),
            ('enterprise', 'llm_chat',             3600, 1000)
        ON CONFLICT (tier, resource) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM rate_limit_config
        WHERE resource IN (
            'tts_gen', 'director_script', 'director_produce',
            'director_ref_images', 'llm_chat'
        )
        """
    )
