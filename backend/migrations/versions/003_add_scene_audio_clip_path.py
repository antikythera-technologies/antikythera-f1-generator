"""Add audio_clip_path to episode_scenes

Revision ID: 003_add_scene_audio_clip_path
Revises: 002_add_scene_dual_frame_columns
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_add_scene_audio_clip_path"
down_revision: Union[str, None] = "002_add_scene_dual_frame_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "episode_scenes",
        sa.Column("audio_clip_path", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episode_scenes", "audio_clip_path")
