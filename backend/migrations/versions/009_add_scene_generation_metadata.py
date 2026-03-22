"""Add generation metadata fields to episode_scenes.

Tracks face reference URL, LoRA/instant-character usage, and
regeneration count for auditability.

Revision ID: 009
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episode_scenes", sa.Column("face_reference_url", sa.String(500), nullable=True))
    op.add_column("episode_scenes", sa.Column("lora_used", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("episode_scenes", sa.Column("instant_character_used", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("episode_scenes", sa.Column("regeneration_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("episode_scenes", "regeneration_count")
    op.drop_column("episode_scenes", "instant_character_used")
    op.drop_column("episode_scenes", "lora_used")
    op.drop_column("episode_scenes", "face_reference_url")
