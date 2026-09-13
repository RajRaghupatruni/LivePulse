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
from app.simulator.comeback import activate_match, clear_demo_data, run_comeback
from app.storage.database import SessionFactory
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
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
        assert focus_by_event["football.match.goal"] == 100
        assert focus_by_event["football.match.red_card"] == 95
        assert focus_by_event["football.match.halftime"] == 52
        assert focus_by_event["football.match.fulltime"] == 30
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


@pytest.mark.asyncio(loop_scope="module")
async def test_outbox_releases_failed_claim_and_retries_after_broker_error() -> None:
    settings = get_settings()
    await ensure_topic()
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"livepulse-retry-test-{uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    event = CanonicalEvent(
        source="retry-test",
        event_type="football.match.scheduled",
        subject_id=f"retry-{uuid7()}",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key=f"retry:{uuid4()}",
        correlation_id=uuid7(),
        payload={"home_team": "Northstar FC", "away_team": "Harbor United"},
    )

    class FailingProducer:
        async def send_and_wait(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("temporary broker failure")

    producer_started = False
    consumer_started = False
    try:
        await producer.start()
        producer_started = True
        await consumer.start()
        consumer_started = True
        # Clear any prior pending rows so the injected failure targets this event.
        await publish_pending_once(producer)
        async with SessionFactory() as session:
            async with session.begin():
                assert await persist_event_and_outbox(session, event)
        assert await publish_pending_once(FailingProducer()) == 0  # type: ignore[arg-type]
        async with SessionFactory() as session:
            row = await session.scalar(
                select(OutboxMessageRow).where(OutboxMessageRow.event_id == event.event_id)
            )
            assert row is not None
            assert row.published_at is None and row.claimed_at is None
            assert row.attempts == 1 and row.last_error == "temporary broker failure"

        assert await publish_pending_once(producer) >= 1
        deadline = asyncio.get_running_loop().time() + 15
        received = False
        while asyncio.get_running_loop().time() < deadline and not received:
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=2)
            except TimeoutError:
                continue
            received = json.loads(message.value).get("event_id") == str(event.event_id)
        assert received
        async with SessionFactory() as session:
            row = await session.scalar(
                select(OutboxMessageRow).where(OutboxMessageRow.event_id == event.event_id)
            )
            assert row is not None and row.published_at is not None
            assert row.attempts == 1 and row.claimed_at is None
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id == event.event_id)
                )


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_duplicate_and_stale_delivery_are_idempotent() -> None:
    match_id = f"idempotency-{uuid7()}"
    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None
    run_id = await activate_match(match_id)
    now = datetime.now(UTC)

    def make_event(version: int, event_type: str, dedupe: str, **payload: object) -> CanonicalEvent:
        return CanonicalEvent(
            source="idempotency-test",
            event_type=event_type,
            subject_id=match_id,
            occurred_at=now,
            observed_at=now,
            version=version,
            dedupe_key=f"{run_id}:{dedupe}",
            correlation_id=run_id,
            payload={"home_team": "Northstar FC", "away_team": "Harbor United", **payload},
        )

    first = make_event(1, "football.match.goal", "one", side="home")
    second = make_event(2, "football.match.kickoff", "two")
    stale = make_event(1, "football.match.goal", "stale", side="away")
    try:
        async with SessionFactory() as session:
            async with session.begin():
                assert await persist_event_and_outbox(session, first)
                assert await persist_event_and_outbox(session, second)
                assert await persist_event_and_outbox(session, stale)

        concurrent = await asyncio.gather(
            process_canonical_event(first), process_canonical_event(first), return_exceptions=True
        )
        assert sum(result is True for result in concurrent) == 1
        assert not await process_canonical_event(first)
        assert await process_canonical_event(second)
        assert await process_canonical_event(stale)

        async with SessionFactory() as session:
            state = await session.get(MatchStateRow, match_id)
            timeline_count = await session.scalar(
                select(func.count())
                .select_from(PulseTimelineRow)
                .where(PulseTimelineRow.subject_id == match_id)
            )
            processed_count = await session.scalar(
                select(func.count())
                .select_from(ConsumerProcessedEventRow)
                .where(
                    ConsumerProcessedEventRow.event_id.in_(
                        [first.event_id, second.event_id, stale.event_id]
                    )
                )
            )
            assert state is not None
            assert (state.home_score, state.away_score, state.version) == (1, 0, 2)
            assert timeline_count == 3 and processed_count == 3
    finally:
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
async def test_late_event_for_inactive_match_still_reaches_durable_timeline() -> None:
    match_id = f"inactive-match-{uuid7()}"
    newer_match_id = f"newer-match-{uuid7()}"
    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None

    run_id = await activate_match(match_id)
    now = datetime.now(UTC)
    event = CanonicalEvent(
        source="idempotency-test",
        event_type="football.match.scheduled",
        subject_id=match_id,
        occurred_at=now,
        observed_at=now,
        version=1,
        dedupe_key=f"{run_id}:late-scheduled",
        correlation_id=run_id,
        payload={
            "home_team": "Northstar FC",
            "away_team": "Harbor United",
            "competition": "Premier League",
        },
    )
    try:
        async with SessionFactory() as session:
            async with session.begin():
                assert await persist_event_and_outbox(session, event)

        # Simulate a new demo being selected while this event is still in broker lag.
        await activate_match(newer_match_id)
        assert await process_canonical_event(event)

        async with SessionFactory() as session:
            assert await session.get(MatchStateRow, match_id) is not None
            timeline_count = await session.scalar(
                select(func.count())
                .select_from(PulseTimelineRow)
                .where(PulseTimelineRow.event_id == event.event_id)
            )
            assert timeline_count == 1
    finally:
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(
                        MatchStateRow.match_id.in_([match_id, newer_match_id])
                    )
                )
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id == event.event_id)
                )
                control = await session.get(DemoControlRow, 1)
                if control and control.active_match_id == newer_match_id:
                    control.active_match_id = previous_match_id


@pytest.mark.asyncio(loop_scope="module")
async def test_demo_reset_preserves_other_sources_and_allows_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulator = __import__("app.simulator.comeback", fromlist=["get_settings"])
    monkeypatch.setattr(simulator, "get_settings", lambda: SimpleNamespace(demo_step_seconds=0))
    demo_match = f"demo-reset-test-{uuid7()}"
    other_match = f"other-reset-test-{uuid7()}"
    demo_run = uuid7()
    other_event = CanonicalEvent(
        source="other-provider",
        event_type="football.match.scheduled",
        subject_id=other_match,
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key=f"other-reset:{uuid4()}",
        correlation_id=uuid7(),
        payload={"home_team": "Other Home", "away_team": "Other Away"},
    )
    demo_event = CanonicalEvent(
        source="demo-football",
        event_type="football.match.scheduled",
        subject_id=demo_match,
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key=f"demo-reset:{uuid4()}",
        correlation_id=demo_run,
        payload={"home_team": "Northstar FC", "away_team": "Harbor United"},
    )
    try:
        await activate_match(demo_match)
        async with SessionFactory() as session:
            async with session.begin():
                assert await persist_event_and_outbox(session, demo_event)
                assert await persist_event_and_outbox(session, other_event)
                session.add_all(
                    [
                        MatchStateRow(
                            match_id=demo_match,
                            home_team="Northstar FC",
                            away_team="Harbor United",
                            competition="Premier League",
                            updated_at=datetime.now(UTC),
                        ),
                        MatchStateRow(
                            match_id=other_match,
                            home_team="Other Home",
                            away_team="Other Away",
                            competition="Other League",
                            updated_at=datetime.now(UTC),
                        ),
                    ]
                )

        await clear_demo_data()
        async with SessionFactory() as session:
            assert await session.get(CanonicalEventRow, demo_event.event_id) is None
            assert await session.get(MatchStateRow, demo_match) is None
            assert await session.get(CanonicalEventRow, other_event.event_id) is not None
            assert await session.get(MatchStateRow, other_match) is not None
            other_outbox = await session.scalar(
                select(OutboxMessageRow).where(OutboxMessageRow.event_id == other_event.event_id)
            )
            assert other_outbox is not None
            control = await session.get(DemoControlRow, 1)
            assert control is not None and control.active_match_id is None

        rerun_match = f"demo-reset-rerun-{uuid7()}"
        rerun_id = await activate_match(rerun_match)
        await run_comeback(rerun_match, rerun_id)
        async with SessionFactory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(CanonicalEventRow)
                .where(CanonicalEventRow.subject_id == rerun_match)
            )
            assert count == 10
    finally:
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(
                        MatchStateRow.match_id.in_([demo_match, other_match])
                    )
                )
                await session.execute(
                    delete(CanonicalEventRow).where(
                        CanonicalEventRow.subject_id.in_([demo_match, other_match])
                    )
                )
                rerun_prefix = "demo-reset-rerun-"
                rerun_ids = select(CanonicalEventRow.event_id).where(
                    CanonicalEventRow.subject_id.like(f"{rerun_prefix}%")
                )
                await session.execute(
                    delete(MatchStateRow).where(
                        MatchStateRow.match_id.like(f"{rerun_prefix}%")
                    )
                )
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id.in_(rerun_ids))
                )
                control = await session.get(DemoControlRow, 1)
                if control:
                    control.active_match_id = None
