"""Persist canonical source on Pulse Timeline rows."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_timeline_source"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pulse_timeline", sa.Column("source", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE pulse_timeline
        SET source = canonical_events.source
        FROM canonical_events
        WHERE pulse_timeline.event_id = canonical_events.event_id
        """
    )
    op.alter_column("pulse_timeline", "source", nullable=False)


def downgrade() -> None:
    op.drop_column("pulse_timeline", "source")
