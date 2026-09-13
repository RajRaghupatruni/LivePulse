"""Weather snapshots, normalized events and shared checkpoint persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.providers.weather.service import weather_state
from app.storage.database import SessionFactory
from app.storage.models import (
    ProviderCheckpointRow,
    WeatherLocationSelectionRow,
)

if TYPE_CHECKING:
    from app.providers.weather.source import WeatherObservation


async def weather_checkpoints(keys: Sequence[str]) -> dict[str, str]:
    if not keys:
        return {}
    async with SessionFactory() as session:
        rows = await session.scalars(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.provider == "weather",
                ProviderCheckpointRow.checkpoint_key.in_(set(keys)),
            )
        )
        return {row.checkpoint_key: row.checkpoint_value for row in rows}


async def _upsert_weather_checkpoint(
    session: AsyncSession, key: str, value: str, observed_at: datetime
) -> None:
    statement_factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = statement_factory(ProviderCheckpointRow).values(
        provider="weather",
        checkpoint_key=key,
        checkpoint_value=value,
        observed_at=observed_at,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["provider", "checkpoint_key"],
            set_={
                "checkpoint_value": statement.excluded.checkpoint_value,
                "observed_at": statement.excluded.observed_at,
                "updated_at": datetime.now(UTC),
            },
        )
    )


async def persist_weather_observation(
    observation: WeatherObservation, *, observed_at: datetime, correlation_id: UUID
) -> None:
    current = observation.current
    serialized = current.model_dump_json()
    baseline_key = f"event_baseline:{observation.location.id}"
    current_key = f"current:{observation.location.id}"
    async with SessionFactory() as session:
        async with session.begin():
            selection = await session.get(WeatherLocationSelectionRow, 1)
            if selection and selection.location_id != observation.location.id:
                return
            event = build_weather_event(
                observation, observed_at=observed_at, correlation_id=correlation_id
            )
            if event:
                await persist_event_and_outbox(session, event)
                await _upsert_weather_checkpoint(session, baseline_key, serialized, observed_at)
            else:
                baseline = await session.scalar(
                    select(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "weather",
                        ProviderCheckpointRow.checkpoint_key == baseline_key,
                    )
                )
                if baseline is None:
                    # A newly selected place starts its own comparison baseline quietly.
                    await _upsert_weather_checkpoint(
                        session, baseline_key, serialized, observed_at
                    )
            await _upsert_weather_checkpoint(session, current_key, serialized, observed_at)
            await _upsert_weather_checkpoint(session, "has_observation", "1", observed_at)
    weather_state.update(
        current, fetched_at=observed_at, location_id=observation.location.id
    )


def build_weather_event(
    observation: WeatherObservation, *, observed_at: datetime, correlation_id: UUID | None = None
) -> CanonicalEvent | None:
    if not observation.meaningful_change:
        return None
    current = observation.current
    return CanonicalEvent(
        source="weather",
        event_type="weather.conditions.updated",
        subject_type="weather_conditions",
        subject_id=str(observation.location.id),
        occurred_at=current.observed_at,
        observed_at=observed_at,
        version=1,
        dedupe_key=observation.dedupe_key,
        correlation_id=correlation_id or uuid7(),
        payload={
            "location": {
                "id": str(observation.location.id),
                "display_name": observation.location.display_name,
                "city": observation.location.city,
                "region": observation.location.region,
                "country": observation.location.country,
                "timezone": observation.location.timezone,
            },
            "current": current.model_dump(mode="json"),
            "change_reasons": list(observation.change_reasons),
        },
    )
