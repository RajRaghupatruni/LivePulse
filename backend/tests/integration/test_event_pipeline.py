import asyncio
import json
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from app.api.routes import timeline as timeline_route
from app.api.routes import websocket_endpoint
from app.core.config import get_settings
from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.outbox.publisher import ensure_topic, publish_pending_once
from app.projections.projector import process_canonical_event
from app.providers.base import PollContext
from app.providers.football.models import FootballFixtureObservation, NormalizedMatchEvent
from app.providers.football.store import FootballCheckpointStore
from app.providers.github.events import GithubChange
from app.providers.github.storage import persist_observations as persist_github_observations
from app.providers.gmail.models import GmailMessageDelta, GmailMessageMetadata, GmailSyncBatch
from app.providers.gmail.sync import (
    HISTORY_CHECKPOINT,
    MESSAGE_STATE_PREFIX,
    ingest_gmail_observations,
)
from app.providers.observations import Observation
from app.providers.spotify.playback import (
    SpotifyEventSink,
    SpotifyPlaybackChange,
    SpotifyPlaybackSnapshot,
)
from app.providers.weather.client import WeatherConditions
from app.providers.weather.location import WeatherLocation
from app.providers.weather.source import WeatherObservation
from app.providers.weather.storage import persist_weather_observation
from app.realtime.manager import realtime
from app.simulator.comeback import activate_match, clear_demo_data, run_comeback
from app.storage.database import SessionFactory
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    DemoControlRow,
    MatchStateRow,
    OutboxMessageRow,
    ProviderCheckpointRow,
    PulseTimelineRow,
    WeatherLocationRow,
    WeatherLocationSelectionRow,
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
async def test_mixed_provider_timeline_and_replay_preserve_match_state() -> None:
    settings = get_settings()
    await ensure_topic()
    match_id = f"mixed-{uuid7()}"
    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None
        cursor_before = await session.scalar(select(func.max(PulseTimelineRow.cursor))) or 0
    run_id = await activate_match(match_id)
    start = datetime.now(UTC)

    def make_event(
        *,
        source: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
        occurred_at: datetime,
        version: int,
        suffix: str,
        payload: dict[str, object],
    ) -> CanonicalEvent:
        return CanonicalEvent(
            source=source,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            occurred_at=occurred_at,
            observed_at=start,
            version=version,
            dedupe_key=f"{run_id}:{suffix}",
            correlation_id=run_id,
            payload=payload,
        )

    football_payload = {
        "home_team": "Northstar FC",
        "away_team": "Harbor United",
        "competition": "Premier League",
        "minute": 0,
    }
    events = [
        make_event(
            source="api-football",
            event_type="football.match.scheduled",
            subject_type="match",
            subject_id=match_id,
            occurred_at=start,
            version=1,
            suffix="football-scheduled",
            payload=football_payload,
        ),
        make_event(
            source="api-football",
            event_type="football.match.kickoff",
            subject_type="match",
            subject_id=match_id,
            occurred_at=start + timedelta(seconds=1),
            version=2,
            suffix="football-kickoff",
            payload={**football_payload, "minute": 0},
        ),
        make_event(
            source="api-football",
            event_type="football.match.goal",
            subject_type="match",
            subject_id=match_id,
            occurred_at=start + timedelta(seconds=2),
            version=3,
            suffix="football-goal",
            payload={**football_payload, "minute": 14, "side": "home"},
        ),
        make_event(
            source="spotify",
            event_type="spotify.track.changed",
            subject_type="spotify_playback",
            subject_id="current",
            occurred_at=start + timedelta(seconds=3),
            version=1,
            suffix="spotify-track",
            payload={"item_uri": "spotify:track:mixed-e2e", "item_name": "Mixed E2E"},
        ),
        make_event(
            source="github",
            event_type="developer.workflow.failed",
            subject_type="workflow_run",
            subject_id="acme/Strata#mixed-e2e",
            occurred_at=start + timedelta(seconds=4),
            version=1,
            suffix="github-workflow",
            payload={"repository": "acme/Strata", "workflow": "CI", "conclusion": "failure"},
        ),
        make_event(
            source="gmail",
            event_type="mail.message.received",
            subject_type="email",
            subject_id="mixed-e2e-message",
            occurred_at=start + timedelta(seconds=5),
            version=1,
            suffix="gmail-message",
            payload={"message_id": "mixed-e2e-message", "subject": "Mixed E2E"},
        ),
        make_event(
            source="weather",
            event_type="weather.conditions.updated",
            subject_type="weather_conditions",
            subject_id="configured-location",
            occurred_at=start + timedelta(seconds=6),
            version=1,
            suffix="weather-change",
            payload={
                "current": {"category": "rain"},
                "change_reasons": ["condition_category_changed"],
            },
        ),
        # A delayed old football fact remains visible in history, but must not
        # replace the newer live-match projection.
        make_event(
            source="api-football",
            event_type="football.match.scheduled",
            subject_type="match",
            subject_id=match_id,
            occurred_at=start + timedelta(seconds=1),
            version=1,
            suffix="football-late-scheduled",
            payload=football_payload,
        ),
    ]
    event_ids = {str(event.event_id) for event in events}
    duplicate_id = str(events[4].event_id)
    notifications = realtime.subscribe()
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"livepulse-mixed-test-{uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    consumer_started = False
    producer_started = False
    try:
        async with SessionFactory() as session:
            async with session.begin():
                for event in events:
                    assert await persist_event_and_outbox(session, event)

        await consumer.start()
        consumer_started = True
        await producer.start()
        producer_started = True
        while await publish_pending_once(producer, batch_size=200):
            pass
        duplicate = events[4]
        await producer.send_and_wait(
            settings.kafka_topic,
            json.dumps(duplicate.model_dump(mode="json")).encode(),
            key=duplicate.subject_id.encode(),
        )

        received_counts: dict[str, int] = {}
        projected_counts: dict[str, int] = {}
        deadline = asyncio.get_running_loop().time() + 25
        target_counts = {event_id: 1 for event_id in event_ids}
        target_counts[duplicate_id] = 2
        while asyncio.get_running_loop().time() < deadline and any(
            received_counts.get(event_id, 0) < count for event_id, count in target_counts.items()
        ):
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=5)
            except TimeoutError:
                continue
            envelope = json.loads(message.value)
            event_id = envelope.get("event_id")
            if event_id not in target_counts:
                continue
            received_counts[event_id] = received_counts.get(event_id, 0) + 1
            parsed = CanonicalEvent.model_validate(envelope)
            applied = await process_canonical_event(parsed)
            projected_counts[event_id] = projected_counts.get(event_id, 0) + int(applied)
            if applied:
                notification = await asyncio.wait_for(notifications.get(), timeout=2)
                assert notification["event_id"] == event_id

        assert received_counts == target_counts
        assert set(projected_counts) == event_ids
        assert all(count == 1 for count in projected_counts.values())

        async with SessionFactory() as session:
            state = await session.get(MatchStateRow, match_id)
            timelines = list(
                await session.scalars(
                    select(PulseTimelineRow)
                    .where(PulseTimelineRow.event_id.in_([event.event_id for event in events]))
                    .order_by(PulseTimelineRow.cursor)
                )
            )
            nonfootball_states = list(
                await session.scalars(
                    select(MatchStateRow).where(
                        MatchStateRow.match_id.in_(
                            [
                                event.subject_id
                                for event in events
                                if not event.event_type.startswith("football.match.")
                            ]
                        )
                    )
                )
            )
            assert state is not None
            assert (state.home_score, state.away_score, state.status, state.version) == (
                1,
                0,
                "live",
                3,
            )
            assert not nonfootball_states
            assert len(timelines) == len(events)
            assert len({row.event_id for row in timelines}) == len(events)
            assert [row.cursor for row in timelines] == sorted(row.cursor for row in timelines)

            history = await timeline_route(limit=200, before=None, session=session)
            assert history["latest_cursor"] >= max(row.cursor for row in timelines)
            assert event_ids <= {item["event_id"] for item in history["items"]}
            expected_observed = {
                str(event.event_id): event.observed_at.isoformat() for event in events
            }
            assert all(
                item["observed_at"] == expected_observed[item["event_id"]]
                for item in history["items"]
                if item["event_id"] in expected_observed
            )
            rest_order = [
                item["event_id"] for item in history["items"] if item["event_id"] in event_ids
            ]
            assert rest_order == [str(row.event_id) for row in reversed(timelines)]

        class ReplaySocket:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []

            async def accept(self) -> None:
                return None

            async def send_json(self, message: dict[str, object]) -> None:
                self.sent.append(message)

        socket = ReplaySocket()
        replay_task = asyncio.create_task(websocket_endpoint(socket, last_cursor=cursor_before))
        replay_deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < replay_deadline and not event_ids <= {
            str(item.get("event_id")) for item in socket.sent
        }:
            await asyncio.sleep(0.01)
        replay_task.cancel()
        with suppress(asyncio.CancelledError):
            await replay_task
        replayed = [item for item in socket.sent if item.get("event_id") in event_ids]
        assert len(replayed) == len(events)
        assert [item["event_id"] for item in replayed] == [str(row.event_id) for row in timelines]
        assert all(item.get("replayed") is True for item in replayed)
        assert all(item.get("observed_at") == start.isoformat() for item in replayed)
        assert {item.get("source") for item in replayed} == {
            "api-football",
            "spotify",
            "github",
            "gmail",
            "weather",
        }
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        realtime.unsubscribe(notifications)
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(MatchStateRow.match_id == match_id)
                )
                await session.execute(
                    delete(CanonicalEventRow).where(
                        CanonicalEventRow.event_id.in_([event.event_id for event in events])
                    )
                )
                control = await session.get(DemoControlRow, 1)
                if control and control.active_match_id == match_id:
                    control.active_match_id = previous_match_id


@pytest.mark.asyncio(loop_scope="module")
async def test_provider_observations_reach_timeline_through_outbox_and_redpanda() -> None:
    settings = get_settings()
    await ensure_topic()
    start = datetime.now(UTC)
    correlation_id = uuid7()
    context = PollContext(correlation_id=correlation_id, scheduled_at=start)
    weather_location = WeatherLocation(
        id=uuid4(),
        display_name="Celina, Texas, United States",
        city="Celina",
        region="Texas",
        country="United States",
        latitude=33.3246,
        longitude=-96.7844,
        timezone="America/Chicago",
    )
    weather_checkpoint_keys = (
        f"current:{weather_location.id}",
        f"event_baseline:{weather_location.id}",
        "has_observation",
    )
    fixture_id = int(uuid7().int % 700_000_000) + 100_000_000
    match_id = f"api-football:fixture:{fixture_id}"
    github_id = f"acme/Strata/workflow-{uuid7()}"
    message_id = uuid7().hex
    thread_id = uuid7().hex
    history_id = str(uuid7().int % 10**30)
    message_state_key = f"{MESSAGE_STATE_PREFIX}{message_id}"
    football_checkpoint_key = f"fixture:{fixture_id}"
    provider_sources = {"api-football", "github", "spotify", "gmail", "weather"}
    event_rows: list[CanonicalEventRow] = []

    async with SessionFactory() as session:
        control = await session.get(DemoControlRow, 1)
        previous_match_id = control.active_match_id if control else None
        previous_checkpoints = list(
            await session.scalars(
                select(ProviderCheckpointRow).where(
                    (ProviderCheckpointRow.provider == "football")
                    & (ProviderCheckpointRow.checkpoint_key == "pending-final")
                    | (
                        (ProviderCheckpointRow.provider == "gmail")
                        & (ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT)
                    )
                    | (
                        (ProviderCheckpointRow.provider == "weather")
                        & ProviderCheckpointRow.checkpoint_key.in_(weather_checkpoint_keys)
                    )
                )
            )
        )
        weather_selection = await session.get(WeatherLocationSelectionRow, 1)
        previous_weather_location_id = (
            weather_selection.location_id if weather_selection else None
        )
        previous_weather_selected_at = (
            weather_selection.selected_at if weather_selection else None
        )
    await activate_match(match_id)

    # Each provider adapter produces its own canonical event and transactional outbox row.
    kickoff = start - timedelta(minutes=14)
    fixture = FootballFixtureObservation(
        fixture_id=fixture_id,
        league_id=39,
        competition="Premier League",
        home_team="Northstar FC",
        away_team="Harbor United",
        kickoff_at=kickoff,
        actual_kickoff_at=kickoff,
        status_code="1H",
        status_label="First Half",
        minute=14,
        home_score=1,
        away_score=0,
        events=(
            NormalizedMatchEvent(
                identity=f"goal:{uuid7()}",
                kind="goal",
                minute=14,
                side="home",
                player="Forward One",
            ),
        ),
    )
    football_observation = Observation[FootballFixtureObservation](
        provider_id="football",
        external_entity_id=fixture.external_entity_id,
        observed_at=start,
        content=fixture,
        correlation_id=correlation_id,
    )
    await FootballCheckpointStore().ingest([football_observation], context)

    github_observation = Observation[GithubChange](
        provider_id="github",
        external_entity_id=github_id,
        observed_at=start + timedelta(seconds=4),
        content=GithubChange(
            event_type="developer.workflow.failed",
            subject_type="workflow_run",
            subject_id=github_id,
            occurred_at=start + timedelta(seconds=4),
            dedupe_key=f"github:mixed:{uuid7()}",
            payload={"repository": "acme/Strata", "workflow": "CI", "conclusion": "failure"},
        ),
        correlation_id=correlation_id,
    )
    await persist_github_observations([github_observation], correlation_id=correlation_id)

    spotify_snapshot = SpotifyPlaybackSnapshot(
        is_playing=True,
        item_type="track",
        item_id=f"track-{uuid7()}",
        item_uri=f"spotify:track:{uuid7().hex}",
        item_name="Mixed provider integration",
        artists=("LivePulse Test Artist",),
        timestamp_ms=int((start + timedelta(seconds=3)).timestamp() * 1000),
    )
    spotify_observation = Observation[SpotifyPlaybackChange](
        provider_id="spotify",
        external_entity_id="current",
        observed_at=start + timedelta(seconds=3),
        content=SpotifyPlaybackChange(
            snapshot=spotify_snapshot,
            event_types=("spotify.playback.started", "spotify.track.changed"),
        ),
        provider_version=str(spotify_snapshot.timestamp_ms),
        correlation_id=correlation_id,
    )
    await SpotifyEventSink().handle("spotify", [spotify_observation], context)

    gmail_metadata = GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        sender="integration@example.test",
        subject="Mixed provider integration",
        received_at=start + timedelta(seconds=6),
        snippet="Bounded integration metadata only",
        is_unread=True,
    )
    gmail_observation = Observation[GmailSyncBatch](
        provider_id="gmail",
        external_entity_id=message_id,
        observed_at=start + timedelta(seconds=7),
        content=GmailSyncBatch(
            history_id=history_id,
            messages=(
                GmailMessageDelta(
                    metadata=gmail_metadata,
                    change="initial",
                    history_id=history_id,
                ),
            ),
        ),
        checkpoint=history_id,
        correlation_id=correlation_id,
    )
    await ingest_gmail_observations("gmail", [gmail_observation], context)

    weather_time = start + timedelta(seconds=8)
    async with SessionFactory() as session:
        async with session.begin():
            session.add(
                WeatherLocationRow(
                    id=weather_location.id,
                    display_name=weather_location.display_name,
                    city=weather_location.city,
                    region=weather_location.region,
                    country=weather_location.country,
                    latitude=weather_location.latitude,
                    longitude=weather_location.longitude,
                    timezone=weather_location.timezone,
                    selected_at=weather_time,
                    last_used_at=weather_time,
                )
            )
            weather_selection = await session.get(WeatherLocationSelectionRow, 1)
            if weather_selection is None:
                weather_selection = WeatherLocationSelectionRow(singleton_id=1)
                session.add(weather_selection)
            weather_selection.location_id = weather_location.id
            weather_selection.selected_at = weather_time
    weather_observation = WeatherObservation(
        location=weather_location,
        current=WeatherConditions(
            observed_at=weather_time,
            local_time=weather_time.isoformat(),
            timezone="America/Chicago",
            temperature_f=68.0,
            apparent_temperature_f=67.0,
            weather_code=61,
            category="rain",
            description="Rain",
            precipitation_in=0.08,
            wind_speed_mph=8.0,
            high_f=72.0,
            low_f=58.0,
            precipitation_probability_max_pct=70,
        ),
        meaningful_change=True,
        change_reasons=("condition_category_changed",),
        dedupe_key=f"weather:mixed:{uuid7()}",
    )
    await persist_weather_observation(
        weather_observation, observed_at=weather_time, correlation_id=correlation_id
    )

    async with SessionFactory() as session:
        event_rows = list(
            await session.scalars(
                select(CanonicalEventRow)
                .where(
                    CanonicalEventRow.source.in_(provider_sources),
                    CanonicalEventRow.ingested_at >= start,
                )
                .order_by(CanonicalEventRow.occurred_at, CanonicalEventRow.event_id)
            )
        )
        assert (
            await session.scalar(
                select(ProviderCheckpointRow.id).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == football_checkpoint_key,
                )
            )
            is not None
        )
        gmail_checkpoint = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.provider == "gmail",
                ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT,
            )
        )
        assert gmail_checkpoint is not None and gmail_checkpoint.checkpoint_value == history_id
        gmail_message_state = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.provider == "gmail",
                ProviderCheckpointRow.checkpoint_key == message_state_key,
            )
        )
        assert gmail_message_state is not None

    events = [
        CanonicalEvent(
            event_id=row.event_id,
            source=row.source,
            event_type=row.event_type,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            occurred_at=row.occurred_at,
            observed_at=row.observed_at,
            ingested_at=row.ingested_at,
            version=row.version,
            dedupe_key=row.dedupe_key,
            schema_version=row.schema_version,
            correlation_id=row.correlation_id,
            payload=row.payload,
        )
        for row in event_rows
    ]
    assert {event.source for event in events} == provider_sources
    assert {event.event_type for event in events} >= {
        "football.match.goal",
        "developer.workflow.failed",
        "spotify.track.changed",
        "mail.message.received",
        "weather.conditions.updated",
    }
    event_ids = {str(event.event_id) for event in events}
    duplicate_event = next(event for event in events if event.source == "github")
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"livepulse-provider-adapters-{uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    consumer_started = False
    producer_started = False
    notifications = realtime.subscribe()
    try:
        await consumer.start()
        consumer_started = True
        await producer.start()
        producer_started = True
        while await publish_pending_once(producer, batch_size=200):
            pass
        await producer.send_and_wait(
            settings.kafka_topic,
            json.dumps(duplicate_event.model_dump(mode="json")).encode(),
            key=duplicate_event.subject_id.encode(),
        )
        target_counts = {event_id: 1 for event_id in event_ids}
        target_counts[str(duplicate_event.event_id)] = 2
        received: dict[str, int] = {}
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline and any(
            received.get(event_id, 0) < count for event_id, count in target_counts.items()
        ):
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=5)
            except TimeoutError:
                continue
            envelope = json.loads(message.value)
            event_id = envelope.get("event_id")
            if event_id not in target_counts:
                continue
            received[event_id] = received.get(event_id, 0) + 1
            parsed = CanonicalEvent.model_validate(envelope)
            if await process_canonical_event(parsed):
                notification = await asyncio.wait_for(notifications.get(), timeout=2)
                assert notification["event_id"] == event_id
        assert received == target_counts

        async with SessionFactory() as session:
            state = await session.get(MatchStateRow, match_id)
            timeline_rows = list(
                await session.scalars(
                    select(PulseTimelineRow)
                    .where(PulseTimelineRow.event_id.in_([event.event_id for event in events]))
                    .order_by(PulseTimelineRow.cursor)
                )
            )
            nonfootball_ids = [
                event.subject_id for event in events if event.source != "api-football"
            ]
            nonfootball_states = list(
                await session.scalars(
                    select(MatchStateRow).where(MatchStateRow.match_id.in_(nonfootball_ids))
                )
            )
            assert state is not None
            assert (state.home_score, state.away_score, state.status, state.version) == (
                1,
                0,
                "live",
                3,
            )
            assert not nonfootball_states
            assert len(timeline_rows) == len(events)
            assert len({row.event_id for row in timeline_rows}) == len(events)
            outbox_rows = list(
                await session.scalars(
                    select(OutboxMessageRow).where(
                        OutboxMessageRow.event_id.in_([event.event_id for event in events])
                    )
                )
            )
            assert len(outbox_rows) == len(events)
            assert all(row.published_at is not None for row in outbox_rows)
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        realtime.unsubscribe(notifications)
        async with SessionFactory() as session:
            async with session.begin():
                await session.execute(
                    delete(MatchStateRow).where(MatchStateRow.match_id == match_id)
                )
                cleanup_rows = list(
                    await session.scalars(
                        select(CanonicalEventRow).where(
                            CanonicalEventRow.source.in_(provider_sources),
                            CanonicalEventRow.ingested_at >= start,
                        )
                    )
                )
                if cleanup_rows:
                    event_row_ids = [row.event_id for row in cleanup_rows]
                    await session.execute(
                        delete(CanonicalEventRow).where(
                            CanonicalEventRow.event_id.in_(event_row_ids)
                        )
                    )
                await session.execute(
                    delete(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "football",
                        ProviderCheckpointRow.checkpoint_key.in_(
                            (football_checkpoint_key, "pending-final")
                        ),
                    )
                )
                await session.execute(
                    delete(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "gmail",
                        ProviderCheckpointRow.checkpoint_key.in_(
                            (HISTORY_CHECKPOINT, message_state_key)
                        ),
                    )
                )
                await session.execute(
                    delete(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "weather",
                        ProviderCheckpointRow.checkpoint_key.in_(weather_checkpoint_keys),
                    )
                )
                for row in previous_checkpoints:
                    session.add(
                        ProviderCheckpointRow(
                            provider=row.provider,
                            checkpoint_key=row.checkpoint_key,
                            checkpoint_value=row.checkpoint_value,
                            observed_at=row.observed_at,
                        )
                    )
                weather_selection = await session.get(WeatherLocationSelectionRow, 1)
                if weather_selection:
                    weather_selection.location_id = previous_weather_location_id
                    weather_selection.selected_at = previous_weather_selected_at
                await session.execute(
                    delete(WeatherLocationRow).where(
                        WeatherLocationRow.id == weather_location.id
                    )
                )
                control = await session.get(DemoControlRow, 1)
                if control and control.active_match_id == match_id:
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
                    delete(MatchStateRow).where(MatchStateRow.match_id.like(f"{rerun_prefix}%"))
                )
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id.in_(rerun_ids))
                )
                control = await session.get(DemoControlRow, 1)
                if control:
                    control.active_match_id = None
