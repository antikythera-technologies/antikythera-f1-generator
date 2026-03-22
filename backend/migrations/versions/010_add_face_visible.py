"""Add face_visible and voiceover_character_id to episode_scenes.

Separates "who is visible" from "who is narrating" so the image
backend can route correctly based on face visibility.

Revision ID: 010
"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episode_scenes", sa.Column("face_visible", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("episode_scenes", sa.Column("voiceover_character_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_scene_voiceover_character",
        "episode_scenes", "characters",
        ["voiceover_character_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_scene_voiceover_character", "episode_scenes", type_="foreignkey")
    op.drop_column("episode_scenes", "voiceover_character_id")
    op.drop_column("episode_scenes", "face_visible")
