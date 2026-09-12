"""Add shared provider connections and synchronization checkpoints.

Revision ID: 0003_provider_foundation
Revises: 0002_timeline_source
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_provider_foundation"
down_revision = "0002_timeline_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="disconnected"),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", name="uq_provider_connections_provider"),
        sa.CheckConstraint(
            "status IN ('disconnected', 'pending', 'connected', 'degraded')",
            name="ck_provider_connections_status",
        ),
    )
    op.create_table(
        "provider_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("checkpoint_key", sa.String(150), nullable=False),
        sa.Column("checkpoint_value", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "checkpoint_key", name="uq_provider_checkpoint_key"),
    )
    op.create_index(
        "ix_provider_checkpoints_updated_at", "provider_checkpoints", ["updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_checkpoints_updated_at", table_name="provider_checkpoints")
    op.drop_table("provider_checkpoints")
    op.drop_table("provider_connections")
