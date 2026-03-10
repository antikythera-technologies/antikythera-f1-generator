"""Add storylines tables

Revision ID: 001_add_storylines
Revises: None
Create Date: 2026-03-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_add_storylines"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    storyline_type_enum = postgresql.ENUM(
        "rivalry", "character_arc", "running_joke", "season_plot", "event_reaction",
        name="storyline_type",
        create_type=True,
    )
    storyline_type_enum.create(op.get_bind(), checkfirst=True)

    storyline_status_enum = postgresql.ENUM(
        "active", "paused", "completed", "archived",
        name="storyline_status",
        create_type=True,
    )
    storyline_status_enum.create(op.get_bind(), checkfirst=True)

    # Create storylines table
    op.create_table(
        "storylines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "storyline_type",
            storyline_type_enum,
            server_default="rivalry",
            nullable=False,
        ),
        sa.Column(
            "status",
            storyline_status_enum,
            server_default="active",
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
        sa.Column("start_race_id", sa.Integer(), sa.ForeignKey("races.id"), nullable=True),
        sa.Column("end_race_id", sa.Integer(), sa.ForeignKey("races.id"), nullable=True),
        sa.Column("plot_points", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("current_beat", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comedy_notes", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Create storyline_characters junction table
    op.create_table(
        "storyline_characters",
        sa.Column(
            "storyline_id",
            sa.Integer(),
            sa.ForeignKey("storylines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # Create storyline_episodes junction table
    op.create_table(
        "storyline_episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "storyline_id",
            sa.Integer(),
            sa.ForeignKey("storylines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("beat_used", sa.Integer(), nullable=True),
        sa.Column("scene_numbers", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("usage_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Create indexes
    op.create_index("ix_storylines_status", "storylines", ["status"])
    op.create_index("ix_storylines_type", "storylines", ["storyline_type"])
    op.create_index("ix_storylines_priority", "storylines", ["priority"])
    op.create_index("ix_storyline_episodes_storyline", "storyline_episodes", ["storyline_id"])
    op.create_index("ix_storyline_episodes_episode", "storyline_episodes", ["episode_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_storyline_episodes_episode")
    op.drop_index("ix_storyline_episodes_storyline")
    op.drop_index("ix_storylines_priority")
    op.drop_index("ix_storylines_type")
    op.drop_index("ix_storylines_status")

    # Drop tables
    op.drop_table("storyline_episodes")
    op.drop_table("storyline_characters")
    op.drop_table("storylines")

    # Drop enum types
    sa.Enum(name="storyline_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="storyline_type").drop(op.get_bind(), checkfirst=True)
