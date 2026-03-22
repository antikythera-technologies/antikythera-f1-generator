"""Add validation fields to episode_scenes.

Revision ID: 008
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episode_scenes", sa.Column("validation_status", sa.String(20), nullable=True))
    op.add_column("episode_scenes", sa.Column("validation_issues", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("episode_scenes", "validation_issues")
    op.drop_column("episode_scenes", "validation_status")
