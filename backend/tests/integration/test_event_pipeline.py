import asyncio
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from app.core.config import get_settings
from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.outbox.publisher import ensure_topic, publish_pending_once
from app.projections.projector import process_canonical_event
from app.realtime.manager import realtime
from app.simulator.comeback import activate_match, run_comeback
from app.storage.database import SessionFactory
from app.storage.models import (
    CanonicalEventRow,
    DemoControlRow,
    MatchStateRow,
    OutboxMessageRow,
    PulseTimelineRow,
)

pytestmark = pytest.mark.skipif(
    os.getenv("LIVEPULSE_INTEGRATION") != "1", reason="requires local PostgreSQL and Redpanda"
)


@pytest.mark.asyncio(loop_scope="module")
async def test_outbox_redpanda_projector_vertical_slice() -> None:
    settings = get_settings()
    await ensure_topic()
    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None
    match_id = f"integration-{uuid7()}"
    run_id = await activate_match(match_id)
    event = CanonicalEvent(
        source="integration-test",
        event_type="football.match.scheduled",
        subject_id=match_id,
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key=f"integration:{run_id}:1",
        correlation_id=run_id,
        payload={"home_team": "Northstar FC", "away_team": "Harbor United", "minute": 0},
    )
    group = f"livepulse-test-{uuid4()}"
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await producer.start()
    try:
        async with SessionFactory() as session:
            async with session.begin():
                assert await persist_event_and_outbox(session, event)
                assert not await persist_event_and_outbox(session, event)
        await publish_pending_once(producer)
        await producer.send_and_wait(
            settings.kafka_topic,
            json.dumps(event.model_dump(mode="json")).encode(),
            key=match_id.encode(),
        )
        deadline = asyncio.get_running_loop().time() + 15
        received: list[CanonicalEvent] = []
        while asyncio.get_running_loop().time() < deadline and len(received) < 2:
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=5)
            except TimeoutError:
                continue
            envelope = json.loads(message.value)
            if envelope["event_id"] == str(event.event_id):
                parsed = CanonicalEvent.model_validate(envelope)
                received.append(parsed)
                await process_canonical_event(parsed)
        assert len(received) == 2  # One outbox publication plus a deliberate duplicate delivery.
        assert not await process_canonical_event(received[-1])
        async with SessionFactory() as session:
            state = await session.get(MatchStateRow, match_id)
            timeline_count = await session.scalar(
                select(func.count())
                .select_from(PulseTimelineRow)
                .where(PulseTimelineRow.event_id == event.event_id)
            )
            stored = await session.get(CanonicalEventRow, event.event_id)
            outbox = await session.scalar(
                select(OutboxMessageRow).where(OutboxMessageRow.event_id == event.event_id)
            )
            assert stored is not None and outbox is not None and outbox.published_at is not None
            assert state is not None and state.status == "scheduled"
            assert timeline_count == 1
    finally:
        await consumer.stop()
        await producer.stop()
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(MatchStateRow.match_id == match_id)
                )
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id == event.event_id)
                )
                control = await session.get(DemoControlRow, 1)
                if control and control.active_match_id == match_id:
                    control.active_match_id = previous_match_id


@pytest.mark.asyncio(loop_scope="module")
async def test_comeback_scenario_reaches_authoritative_final_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    await ensure_topic()
    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None
    match_id = f"scenario-{uuid7()}"
    run_id = await activate_match(match_id)
    simulator = __import__("app.simulator.comeback", fromlist=["get_settings"])
    monkeypatch.setattr(simulator, "get_settings", lambda: SimpleNamespace(demo_step_seconds=0))
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"livepulse-scenario-test-{uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    notifications = realtime.subscribe()
    focus_by_event: dict[str, int] = {}
    await consumer.start()
    await producer.start()
    try:
        await run_comeback(match_id, run_id)
        async with SessionFactory() as session:
            event_count = await session.scalar(
                select(func.count())
                .select_from(CanonicalEventRow)
                .where(CanonicalEventRow.subject_id == match_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxMessageRow)
                .join(CanonicalEventRow, OutboxMessageRow.event_id == CanonicalEventRow.event_id)
                .where(CanonicalEventRow.subject_id == match_id)
            )
            assert event_count == 10 and outbox_count == 10
        await publish_pending_once(producer)
        deadline = asyncio.get_running_loop().time() + 20
        observed: dict[int, CanonicalEvent] = {}
        while asyncio.get_running_loop().time() < deadline and len(observed) < 10:
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=5)
            except TimeoutError:
                continue
            envelope = json.loads(message.value)
            if envelope.get("subject_id") == match_id:
                event = CanonicalEvent.model_validate(envelope)
                observed[event.version] = event
                if await process_canonical_event(event):
                    notification = await asyncio.wait_for(notifications.get(), timeout=2)
                    focus_by_event[event.event_type] = int(notification["attention"])
        assert len(observed) == 10
        assert focus_by_event["football.match.scheduled"] == 40
        assert focus_by_event["football.match.kickoff"] == 70
        assert focus_by_event["football.match.goal"] == 95
        assert focus_by_event["football.match.red_card"] == 95
        assert focus_by_event["football.match.halftime"] == 70
        assert focus_by_event["football.match.fulltime"] == 20
        async with SessionFactory() as session:
            state = await session.get(MatchStateRow, match_id)
            timeline_count = await session.scalar(
                select(func.count())
                .select_from(PulseTimelineRow)
                .where(PulseTimelineRow.subject_id == match_id)
            )
            assert state is not None
            assert (state.home_score, state.away_score, state.status, state.version) == (
                2,
                1,
                "fulltime",
                10,
            )
            assert timeline_count == 10
    finally:
        await consumer.stop()
        await producer.stop()
        realtime.unsubscribe(notifications)
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(MatchStateRow.match_id == match_id)
                )
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.subject_id == match_id)
                )
                control = await session.get(DemoControlRow, 1)
                if control and control.active_match_id == match_id:
                    control.active_match_id = previous_match_id


@pytest.mark.asyncio(loop_scope="module")
async def test_event_rolls_back_when_outbox_insert_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module = __import__("app.events.repository", fromlist=["get_settings"])
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(kafka_topic=None))
    event = CanonicalEvent(
        source="integration-test",
        event_type="football.match.scheduled",
        subject_id="atomicity-check",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key=f"atomicity:{uuid4()}",
        correlation_id=uuid7(),
        payload={"home_team": "Northstar FC", "away_team": "Harbor United"},
    )
    with pytest.raises(IntegrityError):
        async with SessionFactory() as session:
            async with session.begin():
                await persist_event_and_outbox(session, event)
    async with SessionFactory() as session:
        assert await session.get(CanonicalEventRow, event.event_id) is None
