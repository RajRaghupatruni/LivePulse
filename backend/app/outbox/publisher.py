import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.health import report_component
from app.storage.database import SessionFactory
from app.storage.models import OutboxMessageRow

log = logging.getLogger(__name__)


async def ensure_topic() -> None:
    settings = get_settings()
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        await admin.start()
        await admin.create_topics(
            [NewTopic(name=settings.kafka_topic, num_partitions=3, replication_factor=1)]
        )
    except TopicAlreadyExistsError:
        pass
    finally:
        try:
            await admin.close()
        except Exception:
            pass


async def publish_pending_once(producer: AIOKafkaProducer, batch_size: int = 50) -> int:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        async with session.begin():
            rows = list(
                await session.scalars(
                    select(OutboxMessageRow)
                    .where(
                        OutboxMessageRow.published_at.is_(None),
                        or_(
                            OutboxMessageRow.claimed_at.is_(None),
                            OutboxMessageRow.claimed_at < now - timedelta(seconds=30),
                        ),
                    )
                    .order_by(OutboxMessageRow.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.claimed_at = now
        claims = [(r.id, r.event_id, r.topic, r.partition_key, r.payload) for r in rows]

    published = 0
    failures = 0
    for row_id, event_id, topic, key, payload in claims:
        try:
            await producer.send_and_wait(topic, json.dumps(payload).encode(), key=key.encode())
            async with SessionFactory() as session:
                async with session.begin():
                    row = await session.get(OutboxMessageRow, row_id)
                    if row and row.published_at is None:
                        row.published_at = datetime.now(UTC)
                        row.claimed_at = None
                        row.last_error = None
            log.info(
                "outbox message published",
                extra={
                    "event_id": str(event_id),
                    "event_type": payload.get("event_type"),
                    "subject_id": payload.get("subject_id"),
                },
            )
            published += 1
        except Exception as exc:
            failures += 1
            async with SessionFactory() as session:
                async with session.begin():
                    row = await session.get(OutboxMessageRow, row_id)
                    if row:
                        row.attempts += 1
                        row.claimed_at = None
                        row.last_error = str(exc)[:1000]
            log.exception(
                "outbox publication failed",
                extra={
                    "event_id": str(event_id),
                    "event_type": payload.get("event_type"),
                    "subject_id": payload.get("subject_id"),
                    "error_code": "outbox_publish_failed",
                },
            )
    if failures:
        report_component(
            "outbox_publisher",
            "degraded",
            "publish_failed",
            metrics={"published": published, "failed": failures},
        )
    else:
        report_component(
            "outbox_publisher",
            "healthy",
            "poll_complete",
            succeeded=True,
            metrics={"published": published, "failed": 0},
        )
    return published


async def run_publisher() -> None:
    settings = get_settings()
    while True:
        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
        try:
            await ensure_topic()
            await producer.start()
            while True:
                count = await publish_pending_once(producer)
                if count == 0:
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            report_component("outbox_publisher", "degraded", "publisher_disconnected")
            log.exception(
                "outbox publisher disconnected", extra={"error_code": "broker_unavailable"}
            )
            await asyncio.sleep(2)
        finally:
            try:
                await producer.stop()
            except Exception:
                pass
