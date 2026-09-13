"""Persist the selected weather location and a bounded recent list.

Revision ID: 0006_weather_locations
Revises: 0005_dominant_focus
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_weather_locations"
down_revision = "0005_dominant_focus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weather_locations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("region", sa.String(120), nullable=True),
        sa.Column("country", sa.String(120), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_weather_locations_last_used_at", "weather_locations", ["last_used_at"]
    )
    op.create_table(
        "weather_location_selection",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column(
            "location_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("weather_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("singleton_id = 1", name="ck_weather_location_singleton"),
    )
    op.bulk_insert(
        sa.table(
            "weather_location_selection",
            sa.column("singleton_id", sa.Integer()),
            sa.column("location_id", sa.Uuid(as_uuid=True)),
            sa.column("selected_at", sa.DateTime(timezone=True)),
        ),
        [{"singleton_id": 1, "location_id": None, "selected_at": None}],
    )


def downgrade() -> None:
    op.drop_table("weather_location_selection")
    op.drop_index("ix_weather_locations_last_used_at", table_name="weather_locations")
    op.drop_table("weather_locations")
