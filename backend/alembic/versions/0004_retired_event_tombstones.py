"""Add compact event identity tombstones for retention-safe replay.

Revision ID: 0004_retired_event_tombstones
Revises: 0003_provider_foundation
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_retired_event_tombstones"
down_revision = "0003_provider_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retired_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dedupe_hash", name="uq_retired_events_dedupe_hash"),
    )


def downgrade() -> None:
    op.drop_table("retired_events")
