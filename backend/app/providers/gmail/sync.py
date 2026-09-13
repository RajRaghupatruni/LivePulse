"""Bounded Gmail synchronization and atomic canonical-event/checkpoint ingestion."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.providers.base import PollContext, PollSchedule
from app.providers.gmail.client import GmailApiClient, GmailApiError
from app.providers.gmail.models import (
    GmailMessageDelta,
    GmailMessageMetadata,
    GmailSyncBatch,
    safe_event_metadata,
)
from app.providers.gmail.oauth import (
    GmailTokenManager,
    GoogleOAuth,
    OAuthError,
    encryption_key_configured,
)
from app.providers.observations import Observation
from app.providers.status import provider_health
from app.storage.database import SessionFactory
from app.storage.models import CanonicalEventRow, ProviderCheckpointRow

log = logging.getLogger(__name__)
HISTORY_CHECKPOINT = "history_id"
MESSAGE_STATE_PREFIX = "message-state:"
INITIAL_LIMIT = 50
MESSAGE_STATE_LIMIT = 500


class GmailSyncSource:
    provider_id = "gmail"
    schedule = PollSchedule(
        interval=timedelta(minutes=4),
        timeout=timedelta(seconds=90),
        max_backoff=timedelta(minutes=30),
        jitter_ratio=0.1,
    )

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._transport = transport

    def cadence(self, *, context: PollContext) -> timedelta:
        return self.schedule.interval

    async def observe(self, *, context: PollContext) -> tuple[Observation[GmailSyncBatch], ...]:
        if not self._settings.provider_configuration()["gmail"]:
            raise OAuthError("oauth_not_configured")
        if not encryption_key_configured(self._settings):
            raise OAuthError("credential_encryption_unavailable")
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
        ) as http:
            oauth = GoogleOAuth(self._settings, self._session_factory, http)
            tokens = GmailTokenManager(self._settings, self._session_factory, oauth)
            api = GmailApiClient(http, tokens)
            async with self._session_factory() as session:
                checkpoint = await _get_checkpoint(session, HISTORY_CHECKPOINT)
            resynced = False
            if checkpoint is None:
                latest_id, messages = await self._bounded_full_sync(api)
                deltas = [GmailMessageDelta(metadata=item, change="initial") for item in messages]
            else:
                try:
                    latest_id, deltas = await self._incremental_sync(api, checkpoint)
                except GmailApiError as exc:
                    if exc.operation != "history.list" or exc.status_code != 404:
                        raise
                    # Expired history gets one fresh cursor and one bounded scan.
                    latest_id, messages = await self._bounded_full_sync(api)
                    deltas = [
                        GmailMessageDelta(metadata=item, change="initial") for item in messages
                    ]
                    resynced = True
            batch = GmailSyncBatch(history_id=latest_id, messages=tuple(deltas), resynced=resynced)
            return (
                Observation[GmailSyncBatch](
                    provider_id=self.provider_id,
                    external_entity_id="mailbox",
                    observed_at=datetime.now(UTC),
                    content=batch,
                    provider_version=latest_id,
                    checkpoint=latest_id,
                    correlation_id=context.correlation_id,
                ),
            )

    async def _bounded_full_sync(
        self, api: GmailApiClient
    ) -> tuple[str, list[GmailMessageMetadata]]:
        # A pre-scan cursor catches arrivals during this bounded scan on the next history poll.
        baseline = await api.profile_history_id()
        ids = await api.list_messages(limit=INITIAL_LIMIT, category="initial", newer_than_days=14)
        seen: set[str] = set()
        unique_ids: list[str] = []
        for message_id, _thread_id in ids:
            if message_id not in seen:
                seen.add(message_id)
                unique_ids.append(message_id)
        fetched = await _fetch_metadata_batch(api, unique_ids, ignore_missing=True)
        messages = [metadata for metadata in fetched if metadata is not None]
        return baseline, messages

    async def _incremental_sync(
        self, api: GmailApiClient, start_history_id: str
    ) -> tuple[str, list[GmailMessageDelta]]:
        latest_id, history = await api.history(start_history_id=start_history_id)
        additions: set[str] = set()
        label_changes: dict[str, str] = {}
        deletions: dict[str, tuple[str, str | None]] = {}
        for record in history:
            history_id = str(record.get("id", ""))
            for item in record.get("messagesAdded", []) or []:
                message = item.get("message", {}) if isinstance(item, dict) else {}
                message_id = message.get("id") if isinstance(message, dict) else None
                if isinstance(message_id, str):
                    additions.add(message_id)
            for item in record.get("messagesDeleted", []) or []:
                message = item.get("message", {}) if isinstance(item, dict) else {}
                if not isinstance(message, dict):
                    continue
                message_id = message.get("id")
                thread_id = message.get("threadId")
                if isinstance(message_id, str) and history_id.isdigit():
                    deletions[message_id] = (
                        history_id,
                        thread_id if isinstance(thread_id, str) else None,
                    )
            for field in ("labelsAdded", "labelsRemoved"):
                for item in record.get(field, []) or []:
                    message = item.get("message", {}) if isinstance(item, dict) else {}
                    message_id = message.get("id") if isinstance(message, dict) else None
                    if isinstance(message_id, str) and history_id.isdigit():
                        label_changes[message_id] = history_id
        ids = sorted((additions | set(label_changes)) - set(deletions))
        deltas: list[GmailMessageDelta] = []
        fetched = await _fetch_metadata_batch(api, ids, ignore_missing=True)
        for message_id, metadata in zip(ids, fetched, strict=True):
            if metadata is None:
                continue
            if message_id in additions:
                deltas.append(GmailMessageDelta(metadata=metadata, change="message_added"))
            elif message_id in label_changes:
                deltas.append(
                    GmailMessageDelta(
                        metadata=metadata,
                        change="labels_changed",
                        history_id=label_changes[message_id],
                    )
                )
        for message_id, (history_id, thread_id) in deletions.items():
            metadata = await self._previous_message_metadata(message_id, thread_id)
            if metadata is not None:
                deltas.append(
                    GmailMessageDelta(
                        metadata=metadata,
                        change="message_removed",
                        history_id=history_id,
                    )
                )
        return latest_id, deltas

    async def _previous_message_metadata(
        self, message_id: str, fallback_thread_id: str | None
    ) -> GmailMessageMetadata | None:
        async with self._session_factory() as session:
            event = await session.scalar(
                select(CanonicalEventRow).where(
                    CanonicalEventRow.dedupe_key == f"gmail:message.received:{message_id}"
                )
            )
        if event is None:
            return None
        payload = event.payload
        thread_id = payload.get("thread_id") or fallback_thread_id
        received_at = payload.get("received_at")
        if not thread_id or not received_at:
            return None
        return GmailMessageMetadata(
            message_id=message_id,
            thread_id=thread_id,
            sender=payload.get("sender", ""),
            subject=payload.get("subject", "(no subject)"),
            received_at=received_at,
            snippet=payload.get("snippet", ""),
            is_unread=bool(payload.get("unread", False)),
            is_important=bool(payload.get("important", False)),
        )


async def _fetch_metadata_batch(
    api: GmailApiClient, message_ids: list[str], *, ignore_missing: bool
) -> list[GmailMessageMetadata | None]:
    semaphore = asyncio.Semaphore(5)

    async def fetch(message_id: str) -> GmailMessageMetadata | None:
        async with semaphore:
            try:
                return await api.message_metadata(message_id)
            except GmailApiError as exc:
                if ignore_missing and exc.status_code == 404:
                    return None
                raise

    tasks = [asyncio.create_task(fetch(message_id)) for message_id in message_ids]
    try:
        return list(await asyncio.gather(*tasks))
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def ingest_gmail_observations(
    provider: str,
    observations: tuple[Observation[GmailSyncBatch], ...] | list[Observation[GmailSyncBatch]],
    context: PollContext,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
) -> None:
    if provider != "gmail":
        raise ValueError("Gmail ingestion received a different provider")
    latest_message_at: datetime | None = None
    message_count = 0
    async with session_factory() as session:
        async with session.begin():
            for observation in observations:
                await ingest_gmail_batch(session, observation.content, context)
                message_count += len(observation.content.messages)
                if observation.content.messages:
                    observed_at = max(
                        delta.metadata.received_at for delta in observation.content.messages
                    )
                    latest_message_at = (
                        max(latest_message_at, observed_at) if latest_message_at else observed_at
                    )
    provider_health.report(
        "gmail",
        "healthy",
        "sync_succeeded",
        configured=True,
        succeeded=True,
        observed=message_count > 0,
        last_message_observation_at=latest_message_at,
    )


async def ingest_gmail_batch(
    session: AsyncSession, batch: GmailSyncBatch, context: PollContext
) -> None:
    now = datetime.now(UTC)
    for delta in batch.messages:
        metadata = delta.metadata
        prior_state = await _get_checkpoint(session, f"{MESSAGE_STATE_PREFIX}{metadata.message_id}")
        if delta.change == "message_removed":
            removal = _event(
                event_type="mail.thread.updated",
                subject_type="email_thread",
                subject_id=metadata.thread_id,
                occurred_at=metadata.received_at,
                observed_at=now,
                correlation_id=context.correlation_id,
                dedupe_key=(
                    f"gmail:thread.updated:deleted:{delta.history_id}:{metadata.message_id}"
                ),
                metadata=metadata,
                extra_payload={"message_removed": True},
            )
            await persist_event_and_outbox(session, removal)
            await _delete_checkpoint(session, f"{MESSAGE_STATE_PREFIX}{metadata.message_id}")
            continue
        if delta.change in {"initial", "message_added"}:
            received = _event(
                event_type="mail.message.received",
                subject_type="email",
                subject_id=metadata.message_id,
                occurred_at=metadata.received_at,
                observed_at=now,
                correlation_id=context.correlation_id,
                dedupe_key=f"gmail:message.received:{metadata.message_id}",
                metadata=metadata,
            )
            await persist_event_and_outbox(session, received)
            updated = _event(
                event_type="mail.thread.updated",
                subject_type="email_thread",
                subject_id=metadata.thread_id,
                occurred_at=metadata.received_at,
                observed_at=now,
                correlation_id=context.correlation_id,
                dedupe_key=f"gmail:thread.updated:message:{metadata.message_id}",
                metadata=metadata,
            )
            await persist_event_and_outbox(session, updated)
        elif delta.change == "labels_changed" and prior_state is not None:
            try:
                previous = json.loads(prior_state)
            except (ValueError, TypeError):
                previous = {}
            unread_changed = previous.get("unread") != metadata.is_unread
            important_changed = previous.get("important") != metadata.is_important
            if unread_changed or important_changed:
                change_id = delta.history_id or batch.history_id
                update = _event(
                    event_type="mail.thread.updated",
                    subject_type="email_thread",
                    subject_id=metadata.thread_id,
                    occurred_at=metadata.received_at,
                    observed_at=now,
                    correlation_id=context.correlation_id,
                    dedupe_key=(f"gmail:thread.updated:labels:{change_id}:{metadata.message_id}"),
                    metadata=metadata,
                )
                await persist_event_and_outbox(session, update)
        await _set_checkpoint(
            session,
            f"{MESSAGE_STATE_PREFIX}{metadata.message_id}",
            json.dumps(
                {
                    "thread_id": metadata.thread_id,
                    "unread": metadata.is_unread,
                    "important": metadata.is_important,
                },
                separators=(",", ":"),
            ),
            observed_at=now,
        )
    await _set_checkpoint(
        session,
        HISTORY_CHECKPOINT,
        batch.history_id,
        observed_at=now,
    )
    # The checkpoint write shares this SQL transaction with every event/outbox insert.
    await session.flush()
    await _trim_message_states(session)
    if batch.resynced:
        log.info(
            "gmail bounded history recovery completed",
            extra={"provider": "gmail", "message_count": len(batch.messages)},
        )


def _event(
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    occurred_at: datetime,
    observed_at: datetime,
    correlation_id,
    dedupe_key: str,
    metadata: GmailMessageMetadata,
    extra_payload: dict[str, object] | None = None,
) -> CanonicalEvent:
    payload = safe_event_metadata(metadata)
    if extra_payload:
        payload.update(extra_payload)
    return CanonicalEvent(
        source="gmail",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        occurred_at=occurred_at,
        observed_at=observed_at,
        version=1,
        dedupe_key=dedupe_key,
        correlation_id=correlation_id,
        payload=payload,
    )


async def _get_checkpoint(session: AsyncSession, key: str) -> str | None:
    row = await session.scalar(
        select(ProviderCheckpointRow).where(
            ProviderCheckpointRow.provider == "gmail",
            ProviderCheckpointRow.checkpoint_key == key,
        )
    )
    return row.checkpoint_value if row is not None else None


async def _set_checkpoint(
    session: AsyncSession, key: str, value: str, *, observed_at: datetime
) -> None:
    row = await session.scalar(
        select(ProviderCheckpointRow).where(
            ProviderCheckpointRow.provider == "gmail",
            ProviderCheckpointRow.checkpoint_key == key,
        )
    )
    if row is None:
        session.add(
            ProviderCheckpointRow(
                provider="gmail",
                checkpoint_key=key,
                checkpoint_value=value,
                observed_at=observed_at,
            )
        )
    else:
        row.checkpoint_value = value
        row.observed_at = observed_at


async def _delete_checkpoint(session: AsyncSession, key: str) -> None:
    await session.execute(
        delete(ProviderCheckpointRow).where(
            ProviderCheckpointRow.provider == "gmail",
            ProviderCheckpointRow.checkpoint_key == key,
        )
    )


async def _trim_message_states(session: AsyncSession) -> None:
    rows = list(
        await session.scalars(
            select(ProviderCheckpointRow)
            .where(
                ProviderCheckpointRow.provider == "gmail",
                ProviderCheckpointRow.checkpoint_key.like(f"{MESSAGE_STATE_PREFIX}%"),
            )
            .order_by(ProviderCheckpointRow.updated_at.desc(), ProviderCheckpointRow.id.desc())
        )
    )
    if len(rows) > MESSAGE_STATE_LIMIT:
        await session.execute(
            delete(ProviderCheckpointRow).where(
                ProviderCheckpointRow.id.in_([row.id for row in rows[MESSAGE_STATE_LIMIT:]])
            )
        )
