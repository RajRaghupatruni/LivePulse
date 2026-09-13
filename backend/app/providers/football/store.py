"""Durable provider metadata/checkpoints and atomic canonical event ingestion."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.repository import persist_event_and_outbox
from app.providers.base import PollContext
from app.providers.football.ingestion import diff_fixture
from app.providers.football.models import FootballFixtureObservation
from app.providers.observations import Observation
from app.storage.database import SessionFactory
from app.storage.models import ProviderCheckpointRow


class FootballCheckpointStore:
    """Stores small discovery caches and commits each fixture checkpoint with its outbox."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    ) -> None:
        self._session_factory = session_factory

    async def get_json(self, key: str) -> tuple[dict[str, Any], datetime | None] | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == key,
                )
            )
        if row is None:
            return None
        try:
            value = json.loads(row.checkpoint_value)
        except (TypeError, ValueError):
            return None
        return (value, row.observed_at or row.updated_at) if isinstance(value, dict) else None

    async def put_json(
        self, key: str, value: dict[str, Any], *, observed_at: datetime | None = None
    ) -> None:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
        timestamp = (observed_at or datetime.now(UTC)).astimezone(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await _checkpoint_row(session, key)
                if row is None:
                    session.add(
                        ProviderCheckpointRow(
                            provider="football",
                            checkpoint_key=key,
                            checkpoint_value=encoded,
                            observed_at=timestamp,
                        )
                    )
                else:
                    row.checkpoint_value = encoded
                    row.observed_at = timestamp

    async def list_json(self, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "football",
                        ProviderCheckpointRow.checkpoint_key.startswith(prefix),
                    )
                )
            )
        results: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            try:
                value = json.loads(row.checkpoint_value)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                results.append((row.checkpoint_key, value))
        return results

    async def ingest(
        self,
        observations: list[Observation[FootballFixtureObservation]],
        context: PollContext,
    ) -> int:
        if not observations:
            return 0
        persisted_count = 0
        async with self._session_factory() as session:
            async with session.begin():
                pending_row = await _checkpoint_row(session, "pending-final")
                pending_final = set(
                    _decode_pending_index(pending_row.checkpoint_value) if pending_row else []
                )
                for observation in observations:
                    key = f"fixture:{observation.content.fixture_id}"
                    checkpoint = await _checkpoint_row(session, key)
                    previous = (
                        _decode_checkpoint(checkpoint.checkpoint_value) if checkpoint else None
                    )
                    events, state = diff_fixture(
                        previous,
                        observation,
                        correlation_id=context.correlation_id,
                    )
                    for event in events:
                        if await persist_event_and_outbox(session, event):
                            persisted_count += 1
                    encoded = json.dumps(state, separators=(",", ":"), sort_keys=True)
                    if checkpoint is None:
                        session.add(
                            ProviderCheckpointRow(
                                provider="football",
                                checkpoint_key=key,
                                checkpoint_value=encoded,
                                observed_at=observation.observed_at,
                            )
                        )
                    else:
                        checkpoint.checkpoint_value = encoded
                        checkpoint.observed_at = observation.observed_at
                    if state["final_verification_pending"]:
                        pending_final.add(observation.content.fixture_id)
                    else:
                        pending_final.discard(observation.content.fixture_id)
                pending_value = json.dumps(
                    {"fixture_ids": sorted(pending_final)}, separators=(",", ":")
                )
                if pending_row is None:
                    session.add(
                        ProviderCheckpointRow(
                            provider="football",
                            checkpoint_key="pending-final",
                            checkpoint_value=pending_value,
                            observed_at=context.scheduled_at,
                        )
                    )
                else:
                    pending_row.checkpoint_value = pending_value
                    pending_row.observed_at = context.scheduled_at
        return persisted_count


async def _checkpoint_row(session: AsyncSession, key: str) -> ProviderCheckpointRow | None:
    return await session.scalar(
        select(ProviderCheckpointRow)
        .where(
            ProviderCheckpointRow.provider == "football",
            ProviderCheckpointRow.checkpoint_key == key,
        )
        .with_for_update()
    )


def _decode_checkpoint(encoded: str) -> dict[str, Any] | None:
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _decode_pending_index(encoded: str) -> list[int]:
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError):
        return []
    fixture_ids = value.get("fixture_ids", []) if isinstance(value, dict) else []
    return [int(item) for item in fixture_ids if str(item).isdigit()]
