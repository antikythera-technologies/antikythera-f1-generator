"""Add cost tracking fields to scenes.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"


def upgrade():
    op.add_column("episode_scenes", sa.Column("image_cost_usd", sa.Numeric(10, 6), server_default="0"))
    op.add_column("episode_scenes", sa.Column("video_cost_usd", sa.Numeric(10, 6), server_default="0"))
    op.add_column("episode_scenes", sa.Column("image_backend", sa.String(50), nullable=True))


def downgrade():
    op.drop_column("episode_scenes", "image_backend")
    op.drop_column("episode_scenes", "video_cost_usd")
    op.drop_column("episode_scenes", "image_cost_usd")
