"""GitHub event/outbox and opaque checkpoint persistence."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.providers.github.events import GithubChange
from app.providers.observations import Observation
from app.storage.database import SessionFactory
from app.storage.models import ProviderCheckpointRow


async def github_checkpoints(keys: Sequence[str]) -> dict[str, str]:
    if not keys:
        return {}
    async with SessionFactory() as session:
        rows = await session.scalars(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.provider == "github",
                ProviderCheckpointRow.checkpoint_key.in_(set(keys)),
            )
        )
        return {row.checkpoint_key: row.checkpoint_value for row in rows}


async def upsert_checkpoint(
    session: AsyncSession, key: str, value: str, observed_at: datetime
) -> None:
    statement = pg_insert(ProviderCheckpointRow).values(
        provider="github",
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


async def persist_observations(
    observations: Sequence[Observation[GithubChange]], *, correlation_id: UUID
) -> int:
    async with SessionFactory() as session:
        async with session.begin():
            return await persist_observations_in_session(
                session, observations, fallback_correlation_id=correlation_id
            )


async def persist_observations_in_session(
    session: AsyncSession,
    observations: Sequence[Observation[GithubChange]],
    *,
    fallback_correlation_id: UUID,
) -> int:
    persisted = 0
    for observation in observations:
        change = observation.content
        event = CanonicalEvent(
            source="github",
            event_type=change.event_type,
            subject_type=change.subject_type,
            subject_id=change.subject_id,
            occurred_at=change.occurred_at,
            observed_at=observation.observed_at,
            version=1,
            dedupe_key=change.dedupe_key,
            correlation_id=observation.correlation_id or fallback_correlation_id,
            payload=change.payload,
        )
        persisted += await persist_event_and_outbox(session, event)
        if change.checkpoint_key:
            await upsert_checkpoint(
                session,
                change.checkpoint_key,
                change.checkpoint_value,
                observation.observed_at,
            )
    return persisted


async def persist_webhook_delivery(
    *,
    delivery_id: str,
    event_name: str,
    observations: Sequence[Observation[GithubChange]],
    observed_at: datetime,
) -> bool:
    """Claim a delivery and append its changes in one transaction; false means a duplicate."""
    async with SessionFactory() as session:
        async with session.begin():
            marker = pg_insert(ProviderCheckpointRow).values(
                provider="github",
                checkpoint_key=f"delivery:{delivery_id}",
                checkpoint_value=event_name[:255],
                observed_at=observed_at,
            )
            claimed = await session.scalar(
                marker.on_conflict_do_nothing(
                    index_elements=["provider", "checkpoint_key"]
                ).returning(ProviderCheckpointRow.id)
            )
            if claimed is None:
                return False
            await persist_observations_in_session(
                session, observations, fallback_correlation_id=uuid7()
            )
            return True
