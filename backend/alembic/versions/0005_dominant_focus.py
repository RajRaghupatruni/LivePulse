"""Index recent timeline attention candidates by event family and cursor.

Revision ID: 0005_dominant_focus
Revises: 0004_retired_event_tombstones
Create Date: 2026-09-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_dominant_focus"
down_revision: str | None = "0004_retired_event_tombstones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_pulse_timeline_event_type_cursor",
        "pulse_timeline",
        ["event_type", "cursor"],
    )


def downgrade() -> None:
    op.drop_index("ix_pulse_timeline_event_type_cursor", table_name="pulse_timeline")
