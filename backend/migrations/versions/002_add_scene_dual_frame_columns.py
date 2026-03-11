"""Add dual-frame columns to episode_scenes

Revision ID: 002_add_scene_dual_frame_columns
Revises: 001_add_storylines
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_add_scene_dual_frame_columns"
down_revision: Union[str, None] = "001_add_storylines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dual-frame prompts (LLM-generated scene descriptions)
    op.add_column("episode_scenes", sa.Column("start_frame_prompt", sa.Text(), nullable=True))
    op.add_column("episode_scenes", sa.Column("end_frame_prompt", sa.Text(), nullable=True))

    # Final enriched prompts (actually sent to ComfyUI)
    op.add_column("episode_scenes", sa.Column("start_frame_prompt_final", sa.Text(), nullable=True))
    op.add_column("episode_scenes", sa.Column("end_frame_prompt_final", sa.Text(), nullable=True))

    # Dual-frame output paths
    op.add_column("episode_scenes", sa.Column("start_frame_path", sa.String(500), nullable=True))
    op.add_column("episode_scenes", sa.Column("end_frame_path", sa.String(500), nullable=True))

    # Video generation
    op.add_column("episode_scenes", sa.Column("video_prompt", sa.Text(), nullable=True))
    op.add_column("episode_scenes", sa.Column("video_generator", sa.String(50), nullable=True))
    op.add_column("episode_scenes", sa.Column("camera_direction", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("episode_scenes", "camera_direction")
    op.drop_column("episode_scenes", "video_generator")
    op.drop_column("episode_scenes", "video_prompt")
    op.drop_column("episode_scenes", "end_frame_path")
    op.drop_column("episode_scenes", "start_frame_path")
    op.drop_column("episode_scenes", "end_frame_prompt_final")
    op.drop_column("episode_scenes", "start_frame_prompt_final")
    op.drop_column("episode_scenes", "end_frame_prompt")
    op.drop_column("episode_scenes", "start_frame_prompt")
