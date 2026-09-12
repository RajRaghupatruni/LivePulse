"""Initial durable event platform tables.

Revision ID: 0001_initial
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("subject_type", sa.String(50), nullable=False),
        sa.Column("subject_id", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_canonical_events_dedupe_key"),
    )
    op.create_index(
        "ix_canonical_events_subject_version", "canonical_events", ["subject_id", "version"]
    )
    op.create_index("ix_canonical_events_occurred_at", "canonical_events", ["occurred_at"])
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_events.event_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("partition_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_outbox_pending", "outbox_messages", ["published_at", "created_at"])
    op.create_table(
        "match_state",
        sa.Column("match_id", sa.String(100), primary_key=True),
        sa.Column("home_team", sa.String(100), nullable=False),
        sa.Column("away_team", sa.String(100), nullable=False),
        sa.Column("competition", sa.String(100), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("away_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("phase", sa.String(30), nullable=False, server_default="pre_match"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_id", sa.Uuid(), nullable=True),
        sa.Column("last_event_type", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "pulse_timeline",
        sa.Column("cursor", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_events.event_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("subject_id", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_pulse_timeline_cursor", "pulse_timeline", ["cursor"])
    op.create_table(
        "consumer_processed_events",
        sa.Column("consumer_name", sa.String(150), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_events.event_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_processed_events_processed_at", "consumer_processed_events", ["processed_at"]
    )
    op.create_table(
        "demo_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active_match_id", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("demo_control")
    op.drop_index("ix_processed_events_processed_at", table_name="consumer_processed_events")
    op.drop_table("consumer_processed_events")
    op.drop_index("ix_pulse_timeline_cursor", table_name="pulse_timeline")
    op.drop_table("pulse_timeline")
    op.drop_table("match_state")
    op.drop_index("ix_outbox_pending", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_canonical_events_occurred_at", table_name="canonical_events")
    op.drop_index("ix_canonical_events_subject_version", table_name="canonical_events")
    op.drop_table("canonical_events")
