"""Add character_appearances JSON column to episodes.

Stores per-episode outfit/appearance descriptions for each character,
ensuring visual consistency across all scenes in an episode.

Revision ID: 004_add_episode_character_appearances
Revises: 003_add_scene_audio_clip_path
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_add_episode_character_appearances"
down_revision: Union[str, None] = "003_add_scene_audio_clip_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("character_appearances", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "character_appearances")
