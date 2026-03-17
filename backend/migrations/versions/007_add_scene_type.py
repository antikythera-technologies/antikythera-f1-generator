"""Add scene_type column to episode_scenes.

Revision ID: 007
Revises: 006
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "episode_scenes",
        sa.Column("scene_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episode_scenes", "scene_type")
