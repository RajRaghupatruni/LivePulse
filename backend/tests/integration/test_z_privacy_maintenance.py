import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from uuid6 import uuid7

from app.api import routes
from app.core.config import RuntimeMode, Settings, get_settings
from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.maintenance.purge import purge_personal_data
from app.maintenance.retention import apply_retention
from app.projections.projector import process_canonical_event
from app.providers.credentials import CredentialCipher
from app.storage.database import SessionFactory, get_session
from app.storage.models import (
    Base,
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    DemoControlRow,
    MatchStateRow,
    OutboxMessageRow,
    ProviderCheckpointRow,
    ProviderConnectionRow,
    PulseTimelineRow,
    RetiredEventRow,
)

pytestmark = pytest.mark.skipif(
    os.getenv("LIVEPULSE_INTEGRATION") != "1",
    reason="requires local PostgreSQL and Redpanda",
)
_previous_active_match_id: str | None = None
_retention_dedupe_keys: list[str] = []


@pytest_asyncio.fixture(scope="module", autouse=True, loop_scope="module")
async def clean_retention_fixture_rows():
    if os.getenv("LIVEPULSE_INTEGRATION") != "1":
        yield
        return
    yield
    from hashlib import sha256

    async with SessionFactory() as session:
        async with session.begin():
            control = await session.get(DemoControlRow, 1)
            if (
                control
                and control.active_match_id
                and control.active_match_id.startswith("retention-active-")
            ):
                control.active_match_id = _previous_active_match_id
            await session.execute(
                delete(MatchStateRow).where(MatchStateRow.match_id.like("retention-%"))
            )
            await session.execute(
                delete(CanonicalEventRow).where(
                    CanonicalEventRow.source == "privacy-retention-test"
                )
            )
            await session.execute(
                delete(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.checkpoint_key.like("retention-test-%")
                )
            )
            hashes = [sha256(item.encode("utf-8")).hexdigest() for item in _retention_dedupe_keys]
            if hashes:
                await session.execute(
                    delete(RetiredEventRow).where(RetiredEventRow.dedupe_hash.in_(hashes))
                )


def _event(
    event_type: str, subject_id: str, dedupe_key: str, *, ingested_at: datetime
) -> CanonicalEvent:
    football = event_type.startswith("football.match.")
    return CanonicalEvent(
        source="privacy-retention-test",
        event_type=event_type,
        subject_type="match" if football else "thread",
        subject_id=subject_id,
        occurred_at=ingested_at,
        observed_at=ingested_at,
        ingested_at=ingested_at,
        version=1,
        dedupe_key=dedupe_key,
        correlation_id=uuid7(),
        payload=(
            {
                "home_team": "Sanitized Home",
                "away_team": "Sanitized Away",
                "competition": "Test League",
                "minute": 1,
            }
            if football
            else {"subject": "sanitized metadata"}
        ),
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_retention_prunes_old_history_but_preserves_current_state_and_checkpoints() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=400)
    active_id = f"retention-active-{uuid7()}"
    inactive_id = f"retention-finished-{uuid7()}"
    pending_id = f"retention-pending-{uuid7()}"
    checkpoint_key = f"retention-test-{uuid4()}"
    active_event = _event(
        "football.match.kickoff", active_id, f"retention:{active_id}", ingested_at=old
    )
    inactive_event = _event(
        "football.match.fulltime", inactive_id, f"retention:{inactive_id}", ingested_at=old
    )
    history_event = _event(
        "mail.thread.updated", f"thread-{uuid4()}", f"retention:mail:{uuid4()}", ingested_at=old
    )
    pending_event = _event(
        "weather.conditions.updated", pending_id, f"retention:pending:{uuid4()}", ingested_at=old
    )
    _retention_dedupe_keys.extend(
        event.dedupe_key for event in (active_event, inactive_event, history_event, pending_event)
    )

    previous_active: str | None = None
    async with SessionFactory() as session:
        async with session.begin():
            control = await session.get(DemoControlRow, 1)
            previous_active = control.active_match_id if control else None
            if previous_active and previous_active.startswith("retention-active-"):
                previous_active = None
            global _previous_active_match_id
            _previous_active_match_id = previous_active
            if control is None:
                session.add(DemoControlRow(id=1, active_match_id=active_id))
            else:
                control.active_match_id = active_id
            for event in (active_event, inactive_event, history_event, pending_event):
                assert await persist_event_and_outbox(session, event)
            await session.flush()
            for event in (active_event, inactive_event, history_event):
                outbox = await session.scalar(
                    select(OutboxMessageRow).where(OutboxMessageRow.event_id == event.event_id)
                )
                assert outbox is not None
                outbox.published_at = old
            session.add(
                ProviderCheckpointRow(
                    provider="gmail",
                    checkpoint_key=checkpoint_key,
                    checkpoint_value="history-cursor-is-retained",
                    observed_at=old,
                    updated_at=now,
                )
            )

    for event in (active_event, inactive_event, history_event):
        await process_canonical_event(event)

    # Model a fixture projection last advanced beyond the local history window.
    async with SessionFactory() as session:
        async with session.begin():
            stale_state = await session.get(MatchStateRow, inactive_id)
            assert stale_state is not None
            stale_state.updated_at = old

    preview = await apply_retention(now=now, retention_days=365, dry_run=True)
    assert preview.eligible_events >= 2
    assert preview.protected_active_match_events >= 1
    assert preview.deferred_unpublished_events >= 1

    applied = await apply_retention(now=now, retention_days=365, dry_run=False)
    assert applied.eligible_events >= 2
    assert applied.removed_timeline_rows >= 2
    assert applied.removed_inactive_match_projections >= 1

    async with SessionFactory() as session:
        active_state = await session.get(MatchStateRow, active_id)
        inactive_state = await session.get(MatchStateRow, inactive_id)
        active_still_exists = await session.get(CanonicalEventRow, active_event.event_id)
        inactive_deleted = await session.get(CanonicalEventRow, inactive_event.event_id)
        history_deleted = await session.get(CanonicalEventRow, history_event.event_id)
        pending_still_exists = await session.get(CanonicalEventRow, pending_event.event_id)
        checkpoint = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.checkpoint_key == checkpoint_key
            )
        )
        retired = await session.get(RetiredEventRow, history_event.event_id)
        assert active_state is not None and active_state.status == "live"
        assert active_still_exists is not None
        assert inactive_state is None and inactive_deleted is None
        assert history_deleted is None and retired is not None
        assert pending_still_exists is not None
        assert (
            checkpoint is not None and checkpoint.checkpoint_value == "history-cursor-is-retained"
        )

        # Re-ingesting an already-retired dedupe identity remains suppressed.
        duplicate = _event(
            "mail.thread.updated",
            history_event.subject_id,
            history_event.dedupe_key,
            ingested_at=now,
        )
        assert not await persist_event_and_outbox(session, duplicate)


@pytest.mark.asyncio(loop_scope="module")
async def test_purge_removes_postgres_personal_data_and_fresh_app_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    base_url = make_url(settings.runtime_database_url)
    database_name = f"livepulse_purge_{uuid4().hex}"
    admin_engine = create_async_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    isolated_engine = None
    isolated_factory = None
    topic = f"livepulse-purge-test-{uuid4()}"
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    topic_created = False
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        isolated_engine = create_async_engine(
            base_url.set(database=database_name), pool_pre_ping=True
        )
        async with isolated_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        isolated_factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

        await admin.start()
        await admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
        topic_created = True

        event_id = uuid7()
        now = datetime.now(UTC)
        async with isolated_factory() as session:
            async with session.begin():
                session.add(
                    CanonicalEventRow(
                        event_id=event_id,
                        source="gmail",
                        event_type="mail.message.received",
                        subject_type="thread",
                        subject_id="private-thread",
                        occurred_at=now,
                        observed_at=now,
                        ingested_at=now,
                        version=1,
                        dedupe_key="purge-event-dedupe",
                        schema_version=1,
                        correlation_id=uuid7(),
                        payload={"subject": "private subject"},
                    )
                )
                session.add(
                    OutboxMessageRow(
                        event_id=event_id,
                        topic=topic,
                        partition_key="private-thread",
                        payload={"event_id": str(event_id)},
                        published_at=now,
                    )
                )
                session.add(
                    PulseTimelineRow(
                        event_id=event_id,
                        event_type="mail.message.received",
                        source="gmail",
                        subject_id="private-thread",
                        occurred_at=now,
                        payload={"subject": "private subject"},
                    )
                )
                session.add(
                    ConsumerProcessedEventRow(
                        consumer_name="test-projector",
                        event_id=event_id,
                    )
                )
                session.add(
                    MatchStateRow(
                        match_id="purge-match",
                        home_team="Private Home",
                        away_team="Private Away",
                        competition="Private Competition",
                        home_score=1,
                        away_score=0,
                        status="fulltime",
                        minute=90,
                        phase="fulltime",
                        version=1,
                        last_event_id=event_id,
                        last_event_type="football.match.fulltime",
                        updated_at=now,
                    )
                )
                session.add(DemoControlRow(id=1, active_match_id="purge-match"))
                session.add(
                    ProviderCheckpointRow(
                        provider="gmail",
                        checkpoint_key="history-id",
                        checkpoint_value="sensitive-cursor",
                        observed_at=now,
                        updated_at=now,
                    )
                )
                cipher = CredentialCipher(Fernet.generate_key().decode("ascii"))
                session.add(
                    ProviderConnectionRow(
                        provider="gmail",
                        status="connected",
                        encrypted_credentials=cipher.encrypt("sensitive-token"),
                        scopes=["gmail.readonly"],
                        created_at=now,
                        updated_at=now,
                        connected_at=now,
                    )
                )
                session.add(
                    RetiredEventRow(
                        event_id=uuid7(),
                        dedupe_hash="a" * 64,
                        retired_at=now,
                    )
                )

        # Disconnecting one provider clears only its local link and cursor, not history.
        import app.providers.gmail.router as gmail_router

        monkeypatch.setattr(gmail_router, "SessionFactory", isolated_factory)
        assert (await gmail_router.disconnect_gmail())["connected"] is False
        async with isolated_factory() as session:
            connection = await session.scalar(
                select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
            )
            assert connection is not None
            assert connection.status == "disconnected"
            assert connection.encrypted_credentials is None
            assert await session.get(CanonicalEventRow, event_id) is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PulseTimelineRow)
                    .where(PulseTimelineRow.event_id == event_id)
                )
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(ProviderCheckpointRow)) == 0
            )
        async with isolated_factory() as session:
            async with session.begin():
                session.add(
                    ProviderCheckpointRow(
                        provider="github",
                        checkpoint_key="reconciliation-cursor",
                        checkpoint_value="remove-on-purge",
                        observed_at=now,
                        updated_at=now,
                    )
                )

        preview = await purge_personal_data(
            session_factory=isolated_factory,
            include_provider_connections=True,
            dry_run=True,
            broker_topic=topic,
        )
        assert preview.dry_run is True
        assert (
            preview.canonical_events == preview.timeline_rows == preview.provider_checkpoints == 1
        )
        assert preview.provider_connections == 1
        assert preview.broker_history_deleted is False

        report = await purge_personal_data(
            session_factory=isolated_factory,
            include_provider_connections=True,
            dry_run=False,
            broker_topic=topic,
        )
        assert report.broker_history_deleted is True
        async with isolated_factory() as session:
            for model in (
                CanonicalEventRow,
                OutboxMessageRow,
                PulseTimelineRow,
                ConsumerProcessedEventRow,
                MatchStateRow,
                ProviderCheckpointRow,
                ProviderConnectionRow,
                RetiredEventRow,
            ):
                assert await session.scalar(select(func.count()).select_from(model)) == 0
            control = await session.get(DemoControlRow, 1)
            assert control is None or control.active_match_id is None

        # A fresh API process sees no former timeline or match projection after purge.
        monkeypatch_settings = Settings(
            _env_file=None, runtime_mode=RuntimeMode.PERSONAL_LOCAL, run_background_services=False
        )
        original_settings = routes.get_settings
        original_engine = routes.engine
        routes.get_settings = lambda: monkeypatch_settings

        class NoopEngine:
            async def dispose(self) -> None:
                return None

        routes.engine = NoopEngine()

        async def isolated_session():
            async with isolated_factory() as session:
                yield session

        app = routes.app
        app.dependency_overrides[get_session] = isolated_session
        try:
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://localhost"
                ) as client:
                    assert (await client.get("/health/live")).json() == {"status": "live"}
                    assert (await client.get("/api/v1/live-state")).json()["match"] is None
                    assert (await client.get("/api/v1/timeline")).json()["items"] == []
        finally:
            app.dependency_overrides.pop(get_session, None)
            routes.get_settings = original_settings
            routes.engine = original_engine
    finally:
        if topic_created:
            try:
                await admin.delete_topics([topic], timeout_ms=15000)
            except Exception:
                pass
        try:
            await admin.close()
        except Exception:
            pass
        if isolated_engine is not None:
            await isolated_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        await admin_engine.dispose()
