import logging
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.events import CanonicalEvent
from app.storage.models import CanonicalEventRow, OutboxMessageRow, RetiredEventRow

log = logging.getLogger(__name__)


async def persist_event_and_outbox(session: AsyncSession, event: CanonicalEvent) -> bool:
    """Atomically append an event and its matching publish intent; returns False on duplicate."""
    dedupe_hash = _dedupe_hash(event.dedupe_key)
    retired_duplicate = await session.scalar(
        select(RetiredEventRow.event_id).where(RetiredEventRow.dedupe_hash == dedupe_hash)
    )
    if retired_duplicate is not None:
        log.info(
            "retired canonical event duplicate suppressed",
            extra={"event_id": str(retired_duplicate), "event_type": event.event_type},
        )
        return False
    try:
        async with session.begin_nested():
            row = CanonicalEventRow(**event.model_dump())
            session.add(row)
            await session.flush()
            settings = get_settings()
            envelope: dict[str, Any] = event.model_dump(mode="json")
            session.add(
                OutboxMessageRow(
                    event_id=event.event_id,
                    topic=settings.kafka_topic,
                    partition_key=event.subject_id,
                    payload=envelope,
                )
            )
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(CanonicalEventRow.event_id).where(
                CanonicalEventRow.dedupe_key == event.dedupe_key
            )
        )
        if existing is not None:
            log.info(
                "duplicate canonical event suppressed",
                extra={"event_id": str(existing), "event_type": event.event_type},
            )
            return False
        retired_duplicate = await session.scalar(
            select(RetiredEventRow.event_id).where(RetiredEventRow.dedupe_hash == dedupe_hash)
        )
        if retired_duplicate is not None:
            log.info(
                "retired canonical event duplicate suppressed",
                extra={"event_id": str(retired_duplicate), "event_type": event.event_type},
            )
            return False
        raise
    return True


def _dedupe_hash(dedupe_key: str) -> str:
    return sha256(dedupe_key.encode("utf-8")).hexdigest()
