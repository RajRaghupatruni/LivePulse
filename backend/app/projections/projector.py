import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.core.config import get_settings
from app.core.health import report_component
from app.domain.events import CanonicalEvent
from app.domain.focus import focus_for_match
from app.projections.reducer import reduce_match_state
from app.realtime.manager import realtime
from app.storage.database import SessionFactory
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    MatchStateRow,
    PulseTimelineRow,
)

log = logging.getLogger(__name__)
CONSUMER_NAME = "match-state-projector-v1"


async def process_canonical_event(event: CanonicalEvent) -> bool:
    """Apply event once; return True only when a new timeline notification was committed."""
    notification: dict[str, object] | None = None
    async with SessionFactory() as session:
        async with session.begin():
            persisted = await session.get(CanonicalEventRow, event.event_id)
            if persisted is None:
                return False  # Reset may have removed it while an old broker record was in flight.
            already = await session.get(ConsumerProcessedEventRow, (CONSUMER_NAME, event.event_id))
            if already:
                return False
            session.add(
                ConsumerProcessedEventRow(consumer_name=CONSUMER_NAME, event_id=event.event_id)
            )
            next_state = None
            if event.event_type.startswith("football.match."):
                current_row = await session.get(MatchStateRow, event.subject_id)
                current = None
                if current_row:
                    current = {
                        "match_id": current_row.match_id,
                        "home_team": current_row.home_team,
                        "away_team": current_row.away_team,
                        "competition": current_row.competition,
                        "home_score": current_row.home_score,
                        "away_score": current_row.away_score,
                        "status": current_row.status,
                        "minute": current_row.minute,
                        "phase": current_row.phase,
                        "version": current_row.version,
                    }
                if current and event.version <= current["version"]:
                    log.info(
                        "stale event ignored by projector",
                        extra={
                            "event_id": str(event.event_id),
                            "event_type": event.event_type,
                            "subject_id": event.subject_id,
                            "consumer": CONSUMER_NAME,
                        },
                    )
                    return False
                next_state = reduce_match_state(current, event)
                if current_row is None:
                    current_row = MatchStateRow(
                        match_id=event.subject_id, **_match_state_fields(next_state)
                    )
                    session.add(current_row)
                else:
                    for key, value in _match_state_fields(next_state).items():
                        setattr(current_row, key, value)
            timeline = PulseTimelineRow(
                event_id=event.event_id,
                event_type=event.event_type,
                source=event.source,
                subject_id=event.subject_id,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            session.add(timeline)
            await session.flush()
            focus = (
                focus_for_match(
                    str(next_state["status"]),
                    event.event_type,
                    next_state["updated_at"],  # type: ignore[arg-type]
                    source="football",
                    subject_id=event.subject_id,
                )
                if next_state
                else focus_for_match("idle", None, source=event.source, subject_id=event.subject_id)
            )
            notification = {
                "type": "timeline.item",
                "cursor": timeline.cursor,
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "source": event.source,
                "subject_id": event.subject_id,
                "timestamp": event.occurred_at.isoformat(),
                "payload": event.payload,
                "attention": focus.score,
                "focus": focus.model_dump(mode="json"),
            }
            if next_state is not None:
                notification["state"] = _public_state(next_state)
    if notification:
        await realtime.publish(notification)
        log.info(
            "event projected",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "subject_id": event.subject_id,
                "consumer": CONSUMER_NAME,
            },
        )
        return True
    return False


def _match_state_fields(state: dict[str, object]) -> dict[str, object]:
    return {
        key: state[key]
        for key in (
            "home_team",
            "away_team",
            "competition",
            "home_score",
            "away_score",
            "status",
            "minute",
            "phase",
            "version",
            "last_event_id",
            "last_event_type",
            "updated_at",
        )
    }


def _public_state(state: dict[str, object]) -> dict[str, object]:
    result = dict(state)
    result["last_event_id"] = str(result["last_event_id"])
    result["updated_at"] = result["updated_at"].isoformat()  # type: ignore[union-attr]
    return result


async def _process_message(message: object) -> None:
    try:
        payload = json.loads(message.value)  # type: ignore[attr-defined]
        event = CanonicalEvent.model_validate(payload)
        await process_canonical_event(event)
    except Exception:
        log.exception(
            "projector rejected broker message",
            extra={"consumer": CONSUMER_NAME, "error_code": "invalid_event"},
        )
        raise


async def run_projector() -> None:
    settings = get_settings()
    while True:
        consumer = AIOKafkaConsumer(
            settings.kafka_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        try:
            await consumer.start()
            report_component("projector", "healthy", "consumer_connected", succeeded=True)
            while True:
                batches = await consumer.getmany(timeout_ms=1000, max_records=50)
                for messages in batches.values():
                    for message in messages:
                        await _process_message(message)
                if any(batches.values()):
                    # getmany advances local positions for the entire batch; commit
                    # only after every record in it has durably projected.
                    await consumer.commit()
                report_component("projector", "healthy", "poll_complete", succeeded=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            report_component("projector", "degraded", "consumer_disconnected")
            log.exception(
                "projector disconnected",
                extra={"consumer": CONSUMER_NAME, "error_code": "consumer_failed"},
            )
            await asyncio.sleep(2)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass
