from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

from app.providers.credentials import EncryptedCredentials


class Base(DeclarativeBase):
    pass


json_type = MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql"))
scopes_type = JSON().with_variant(JSONB, "postgresql")


class EncryptedCredentialsType(TypeDecorator[EncryptedCredentials]):
    """Refuse plaintext strings at the ORM-to-database boundary."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: EncryptedCredentials | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, EncryptedCredentials):
            raise TypeError("provider credentials must be encrypted before persistence")
        return value.token

    def process_result_value(self, value: str | None, dialect: Any) -> EncryptedCredentials | None:
        return EncryptedCredentials(value) if value is not None else None


class CanonicalEventRow(Base):
    __tablename__ = "canonical_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_canonical_events_dedupe_key"),
        Index("ix_canonical_events_subject_version", "subject_id", "version"),
        Index("ix_canonical_events_occurred_at", "occurred_at"),
    )

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    version: Mapped[int] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    schema_version: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[UUID]
    payload: Mapped[dict[str, Any]] = mapped_column(json_type)


class OutboxMessageRow(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("ix_outbox_pending", "published_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.event_id", ondelete="CASCADE"), unique=True
    )
    topic: Mapped[str] = mapped_column(String(200))
    partition_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(json_type)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MatchStateRow(Base):
    __tablename__ = "match_state"

    match_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    home_team: Mapped[str] = mapped_column(String(100))
    away_team: Mapped[str] = mapped_column(String(100))
    competition: Mapped[str] = mapped_column(String(100))
    home_score: Mapped[int] = mapped_column(Integer, default=0)
    away_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    minute: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str] = mapped_column(String(30), default="pre_match")
    version: Mapped[int] = mapped_column(Integer, default=0)
    last_event_id: Mapped[UUID | None] = mapped_column(nullable=True)
    last_event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PulseTimelineRow(Base):
    __tablename__ = "pulse_timeline"
    __table_args__ = (
        Index("ix_pulse_timeline_cursor", "cursor"),
        Index("ix_pulse_timeline_event_type_cursor", "event_type", "cursor"),
    )

    cursor: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.event_id", ondelete="CASCADE"), unique=True
    )
    event_type: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(100))
    subject_id: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(json_type)


class ConsumerProcessedEventRow(Base):
    __tablename__ = "consumer_processed_events"
    __table_args__ = (Index("ix_processed_events_processed_at", "processed_at"),)

    consumer_name: Mapped[str] = mapped_column(String(150), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.event_id", ondelete="CASCADE"), primary_key=True
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RetiredEventRow(Base):
    """Privacy-minimal tombstones preserve delivery/dedupe identity after retention."""

    __tablename__ = "retired_events"
    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_retired_events_dedupe_hash"),)

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DemoControlRow(Base):
    __tablename__ = "demo_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_match_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ProviderConnectionRow(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("provider", name="uq_provider_connections_provider"),
        CheckConstraint(
            "status IN ('disconnected', 'pending', 'connected', 'degraded')",
            name="ck_provider_connections_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="disconnected")
    encrypted_credentials: Mapped[EncryptedCredentials | None] = mapped_column(
        EncryptedCredentialsType(), nullable=True
    )
    scopes: Mapped[list[str]] = mapped_column(scopes_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"ProviderConnectionRow(provider={self.provider!r}, status={self.status!r})"


class ProviderCheckpointRow(Base):
    __tablename__ = "provider_checkpoints"
    __table_args__ = (
        UniqueConstraint("provider", "checkpoint_key", name="uq_provider_checkpoint_key"),
        Index("ix_provider_checkpoints_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    checkpoint_key: Mapped[str] = mapped_column(String(150), nullable=False)
    checkpoint_value: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class WeatherLocationRow(Base):
    __tablename__ = "weather_locations"
    __table_args__ = (Index("ix_weather_locations_last_used_at", "last_used_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WeatherLocationSelectionRow(Base):
    __tablename__ = "weather_location_selection"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_weather_location_singleton"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("weather_locations.id", ondelete="SET NULL"), nullable=True
    )
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
