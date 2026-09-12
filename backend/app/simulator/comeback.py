import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from uuid6 import uuid7

from app.core.config import get_settings
from app.domain.events import FootballEventType, utc_now
from app.events.repository import persist_event_and_outbox
from app.ingestion.normalize import ProviderObservation, normalize_football_observation
from app.storage.database import SessionFactory
from app.storage.models import DemoControlRow

log = logging.getLogger(__name__)

SCENARIO = [
    (FootballEventType.SCHEDULED, 0, None, None),
    (FootballEventType.KICKOFF, 0, None, None),
    (FootballEventType.GOAL, 28, "home", "M. Vale"),
    (FootballEventType.YELLOW_CARD, 37, "away", "J. Reed"),
    (FootballEventType.HALFTIME, 45, None, None),
    (FootballEventType.SECOND_HALF, 45, None, None),
    (FootballEventType.GOAL, 58, "away", "A. Noor"),
    (FootballEventType.RED_CARD, 71, "away", "J. Reed"),
    (FootballEventType.GOAL, 84, "home", "M. Vale"),
    (FootballEventType.FULLTIME, 90, None, None),
]


async def activate_match(match_id: str) -> UUID:
    run_id = uuid7()
    async with SessionFactory() as session:
        async with session.begin():
            control = await session.get(DemoControlRow, 1)
            if control is None:
                session.add(DemoControlRow(id=1, active_match_id=match_id))
            else:
                control.active_match_id = match_id
    return run_id


async def run_comeback(match_id: str, run_id: UUID) -> None:
    settings = get_settings()
    for sequence, (event_type, minute, side, player) in enumerate(SCENARIO, start=1):
        now = datetime.now(UTC)
        observation = ProviderObservation(
            event_type=event_type,
            match_id=match_id,
            run_id=run_id,
            sequence=sequence,
            occurred_at=now,
            observed_at=utc_now(),
            payload={
                "home_team": "Northstar FC",
                "away_team": "Harbor United",
                "competition": "Premier League",
                "minute": minute,
                "side": side,
                "player": player,
            },
        )
        event = normalize_football_observation(observation)
        async with SessionFactory() as session:
            async with session.begin():
                control = await session.get(DemoControlRow, 1)
                if control is None or control.active_match_id != match_id:
                    return
                await persist_event_and_outbox(session, event)
        log.info(
            "simulator observation normalized and persisted",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "subject_id": event.subject_id,
                "correlation_id": str(run_id),
            },
        )
        if sequence < len(SCENARIO):
            await asyncio.sleep(settings.demo_step_seconds)


async def clear_demo_data() -> None:
    # Keep reset scoped to simulator data; future providers must retain their history.
    from app.storage.models import (
        CanonicalEventRow,
        MatchStateRow,
    )

    async with SessionFactory() as session:
        async with session.begin():
            demo_matches = select(CanonicalEventRow.subject_id).where(
                CanonicalEventRow.source == "demo-football"
            )
            await session.execute(
                delete(MatchStateRow).where(MatchStateRow.match_id.in_(demo_matches))
            )
            # Outbox, timeline, and processed-event rows cascade from canonical_events.
            await session.execute(
                delete(CanonicalEventRow).where(CanonicalEventRow.source == "demo-football")
            )
            control = await session.get(DemoControlRow, 1)
            if control is None:
                session.add(DemoControlRow(id=1, active_match_id=None))
            else:
                control.active_match_id = None
