"""Add race results tables for automated result ingestion.

Three tables:
- race_results: Individual driver positions per session
- race_incidents: Key incidents (safety cars, crashes, penalties)
- race_session_summaries: High-level stats (overtakes, podium, weather)

Revision ID: 005_add_race_results
Revises: 004_add_episode_character_appearances
"""

from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_add_race_results"
down_revision: Union[str, None] = "004_add_episode_character_appearances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create session_type enum
    session_type = sa.Enum(
        'fp1', 'fp2', 'fp3', 'qualifying', 'sprint_qualifying', 'sprint', 'race',
        name='session_type',
    )
    session_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "race_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("race_id", sa.Integer, sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_type", session_type, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("driver_name", sa.String(100), nullable=False),
        sa.Column("driver_display_name", sa.String(100)),
        sa.Column("driver_number", sa.Integer),
        sa.Column("team", sa.String(100)),
        sa.Column("time_or_gap", sa.String(50)),
        sa.Column("laps_completed", sa.Integer),
        sa.Column("grid_position", sa.Integer),
        sa.Column("positions_gained", sa.Integer),
        sa.Column("status", sa.String(50), default="Finished"),
        sa.Column("is_dnf", sa.Boolean, default=False),
        sa.Column("dnf_reason", sa.String(200)),
        sa.Column("fastest_lap", sa.Boolean, default=False),
        sa.Column("fastest_lap_time", sa.String(20)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "race_incidents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("race_id", sa.Integer, sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_type", session_type, nullable=False),
        sa.Column("lap", sa.Integer),
        sa.Column("incident_type", sa.String(50)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("drivers_involved", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "race_session_summaries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("race_id", sa.Integer, sa.ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_type", session_type, nullable=False),
        sa.Column("total_overtakes", sa.Integer),
        sa.Column("safety_car_periods", sa.Integer, default=0),
        sa.Column("vsc_periods", sa.Integer, default=0),
        sa.Column("red_flag_periods", sa.Integer, default=0),
        sa.Column("total_dnfs", sa.Integer, default=0),
        sa.Column("rain", sa.Boolean, default=False),
        sa.Column("winner", sa.String(100)),
        sa.Column("second", sa.String(100)),
        sa.Column("third", sa.String(100)),
        sa.Column("raw_api_response", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("race_session_summaries")
    op.drop_table("race_incidents")
    op.drop_table("race_results")
    sa.Enum(name='session_type').drop(op.get_bind(), checkfirst=True)
