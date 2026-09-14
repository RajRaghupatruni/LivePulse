import json
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core.config import Settings
from app.domain.events import CanonicalEvent
from app.providers.base import PollContext
from app.providers.gmail.client import GmailApiClient
from app.providers.gmail.models import (
    GmailMessageBody,
    GmailMessageDelta,
    GmailMessageMetadata,
    GmailSyncBatch,
)
from app.providers.gmail.oauth import (
    GMAIL_READONLY_SCOPE,
    GmailTokenManager,
    GoogleOAuth,
    OAuthAccessLogRedactionFilter,
    OAuthError,
    OAuthStateStore,
    StoredTokenSet,
    _decrypt_tokens,
    _encrypt_tokens,
)
from app.providers.gmail.router import oauth_callback
from app.providers.gmail.service import GmailReadOnlyService
from app.providers.gmail.sync import (
    HISTORY_CHECKPOINT,
    MESSAGE_STATE_PREFIX,
    GmailSyncSource,
    ingest_gmail_observations,
)
from app.providers.scheduler import RetryAfterError, next_poll_delay
from app.providers.status import ProviderHealthRegistry
from app.storage.models import (
    Base,
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    OutboxMessageRow,
    ProviderCheckpointRow,
    ProviderConnectionRow,
    PulseTimelineRow,
)


@pytest.fixture
async def db_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def google_settings() -> Settings:
    return Settings(
        _env_file=None,
        google_client_id="client-id",
        google_client_secret="server-only-client-secret",
        google_redirect_uri="http://127.0.0.1:8000/api/v1/providers/gmail/oauth/callback",
        credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def _context() -> PollContext:
    return PollContext(correlation_id=uuid4(), scheduled_at=datetime.now(UTC))


def _metadata(
    message_id: str = "msg1",
    thread_id: str = "thread1",
    *,
    unread: bool = True,
    important: bool = False,
) -> GmailMessageMetadata:
    return GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        sender="A Sender <sender@example.test>",
        subject="A subject",
        received_at=datetime(2026, 9, 12, 10, tzinfo=UTC),
        snippet="Safe dashboard preview",
        is_unread=unread,
        is_important=important,
    )


async def _seed_connection(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    access_token: str = "old-access-token",
    refresh_token: str = "refresh-token-private",
    expires_at: datetime | None = None,
) -> None:
    encrypted = _encrypt_tokens(
        settings,
        StoredTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.scalar(
                select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
            )
            if row is None:
                row = ProviderConnectionRow(provider="gmail")
                session.add(row)
            row.status = "connected"
            row.encrypted_credentials = encrypted
            row.scopes = [GMAIL_READONLY_SCOPE]


async def _row_count(factory, model, **filters) -> int:
    async with factory() as session:
        query = select(func.count()).select_from(model)
        for key, value in filters.items():
            query = query.where(getattr(model, key) == value)
        return int(await session.scalar(query) or 0)


def _oauth_token_response(
    *, access: str = "access-private", refresh: str | None = "refresh-private"
):
    result = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": GMAIL_READONLY_SCOPE,
    }
    if refresh:
        result["refresh_token"] = refresh
    return result


@pytest.mark.asyncio
async def test_oauth_state_is_signed_expiring_and_one_time() -> None:
    store = OAuthStateStore("server-secret", ttl=timedelta(milliseconds=10))
    state = await store.issue()
    assert len(state.split(".")[0]) >= 40
    assert await store.consume(state)
    assert not await store.consume(state)

    expired = await store.issue()
    import asyncio

    await asyncio.sleep(0.02)
    assert not await store.consume(expired)
    assert not await store.consume("forged-state")


@pytest.mark.asyncio
async def test_authorization_code_exchange_persists_only_encrypted_readonly_tokens(
    db_factory, google_settings
) -> None:
    submitted: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        submitted.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json=_oauth_token_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        url = await oauth.begin()
        params = parse_qs(urlparse(url).query)
        assert params["scope"] == [GMAIL_READONLY_SCOPE]
        assert params["redirect_uri"] == [google_settings.google_redirect_uri]
        assert params["response_type"] == ["code"]
        assert params["access_type"] == ["offline"]
        assert "gmail.modify" not in url and "mail.google.com" not in url
        assert "server-only-client-secret" not in url
        state = params["state"][0]
        await oauth.complete(state=state, code="mock-authorization-code")
        with pytest.raises(OAuthError, match="oauth_state_invalid"):
            await oauth.complete(state=state, code="replay-code")

    assert submitted[0]["code"] == ["mock-authorization-code"]
    assert submitted[0]["client_secret"] == ["server-only-client-secret"]
    async with db_factory() as session:
        row = await session.scalar(
            select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
        )
        assert row is not None and row.status == "connected"
        assert row.scopes == [GMAIL_READONLY_SCOPE]
        ciphertext = row.encrypted_credentials
        assert ciphertext is not None
        assert "access-private" not in repr(ciphertext)
        stored = _decrypt_tokens(google_settings, ciphertext)
        assert stored.access_token.get_secret_value() == "access-private"
        assert stored.refresh_token.get_secret_value() == "refresh-private"


@pytest.mark.asyncio
async def test_gmail_oauth_callback_redirects_to_frontend_with_bounded_results(
    monkeypatch, google_settings
) -> None:
    import importlib

    gmail_router = importlib.import_module("app.providers.gmail.router")
    issued = {"denied-state", "incomplete-state", "failed-state", "success-state"}
    completed: list[tuple[str, str]] = []

    class StateStore:
        async def consume(self, state: str) -> bool:
            if state not in issued:
                return False
            issued.remove(state)
            return True

    states = StateStore()

    class FakeGoogleOAuth:
        def __init__(self, *_args, **_kwargs) -> None:
            self.states = states

        async def complete(self, *, state: str, code: str) -> None:
            if not await self.states.consume(state):
                raise OAuthError("oauth_state_invalid")
            completed.append((state, code))
            if code == "exchange-failure-code":
                raise OAuthError("authorization_exchange_failed")

    monkeypatch.setattr(gmail_router, "get_settings", lambda: google_settings)
    monkeypatch.setattr(gmail_router, "GoogleOAuth", FakeGoogleOAuth)

    async def invoke(query: dict[str, str]):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/providers/gmail/oauth/callback",
                "query_string": urlencode(query).encode(),
                "headers": [],
            }
        )
        response = await oauth_callback(request)
        assert response.status_code == 303
        return urlparse(response.headers["location"])

    denied = await invoke(
        {
            "state": "denied-state",
            "error": "access_denied",
            "error_description": "provider-private-detail",
        }
    )
    assert denied.scheme == "http" and denied.netloc == "127.0.0.1:5173"
    assert parse_qs(denied.query) == {
        "gmail": ["error"],
        "reason": ["authorization_denied"],
    }
    assert "provider-private-detail" not in denied.geturl()

    invalid_state = await invoke({"state": "forged-state", "error": "access_denied"})
    assert parse_qs(invalid_state.query) == {
        "gmail": ["error"],
        "reason": ["state_invalid"],
    }

    incomplete = await invoke({"state": "incomplete-state"})
    assert parse_qs(incomplete.query) == {
        "gmail": ["error"],
        "reason": ["authorization_incomplete"],
    }

    failed = await invoke({"state": "failed-state", "code": "exchange-failure-code"})
    assert parse_qs(failed.query) == {
        "gmail": ["error"],
        "reason": ["connection_failed"],
    }
    assert "exchange-failure-code" not in failed.geturl()

    connected = await invoke({"state": "success-state", "code": "one-time-code"})
    assert connected.scheme == "http" and connected.netloc == "127.0.0.1:5173"
    assert connected.path == "/"
    assert parse_qs(connected.query) == {"gmail": ["connected"]}
    assert "127.0.0.1:8000" not in connected.geturl()
    assert completed == [
        ("failed-state", "exchange-failure-code"),
        ("success-state", "one-time-code"),
    ]


@pytest.mark.asyncio
async def test_oauth_rejects_broader_scopes_and_missing_setup(google_settings, db_factory) -> None:
    async def begin_with_scope(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                **_oauth_token_response(),
                "scope": f"{GMAIL_READONLY_SCOPE} https://www.googleapis.com/auth/gmail.modify",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(begin_with_scope)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        state = await oauth.states.issue()
        with pytest.raises(OAuthError, match="read_only_scope_required"):
            await oauth.complete(state=state, code="code")

    missing = Settings(_env_file=None)
    with pytest.raises(OAuthError, match="oauth_not_configured"):
        async with httpx.AsyncClient() as http:
            await GoogleOAuth(missing, db_factory, http).begin()
    assert ProviderHealthRegistry().snapshot(missing)["gmail"]["status"] == "disconnected"
    source = GmailSyncSource(settings=missing, session_factory=db_factory)
    with pytest.raises(OAuthError, match="oauth_not_configured"):
        await source.observe(context=_context())
    no_vault = Settings(
        _env_file=None,
        google_client_id="client-id",
        google_client_secret="secret-without-vault",
        google_redirect_uri="http://localhost/callback",
        credential_encryption_key="   ",
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(OAuthError, match="credential_encryption_unavailable"):
            await GoogleOAuth(no_vault, db_factory, http).begin()


@pytest.mark.asyncio
async def test_refresh_lifecycle_updates_ciphertext_without_exposing_tokens(
    db_factory, google_settings
) -> None:
    await _seed_connection(
        db_factory,
        google_settings,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            200, json=_oauth_token_response(access="rotated-access", refresh=None)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        manager = GmailTokenManager(google_settings, db_factory, oauth)
        token = await manager.access_token()
        assert token.get_secret_value() == "rotated-access"

    assert requests == ["/token"]
    async with db_factory() as session:
        row = await session.scalar(
            select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
        )
        assert row is not None and row.encrypted_credentials is not None
        assert "rotated-access" not in repr(row)
        decrypted = _decrypt_tokens(google_settings, row.encrypted_credentials)
        assert decrypted.access_token.get_secret_value() == "rotated-access"
        assert decrypted.refresh_token.get_secret_value() == "refresh-token-private"


@pytest.mark.asyncio
async def test_401_refreshes_once_and_invalid_grant_requires_reconnect(
    db_factory, google_settings
) -> None:
    await _seed_connection(db_factory, google_settings)
    calls: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization")
        calls.append((request.url.path, token))
        if request.url.path.endswith("/profile"):
            if token == "Bearer old-access-token":
                return httpx.Response(401, json={"error": "expired"})
            return httpx.Response(200, json={"historyId": "1234"})
        if request.url.path == "/token":
            return httpx.Response(
                200, json=_oauth_token_response(access="new-access", refresh=None)
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        api = GmailApiClient(http, GmailTokenManager(google_settings, db_factory, oauth))
        assert await api.profile_history_id() == "1234"
    assert [path.rsplit("/", 1)[-1] for path, _ in calls] == [
        "profile",
        "token",
        "profile",
    ]
    assert calls[0][1] == "Bearer old-access-token"
    assert calls[2][1] == "Bearer new-access"

    def rejected_refresh(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/profile"):
            return httpx.Response(401)
        return httpx.Response(400, json={"error": "invalid_grant"})

    await _seed_connection(db_factory, google_settings, access_token="another-access")
    async with httpx.AsyncClient(transport=httpx.MockTransport(rejected_refresh)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        api = GmailApiClient(http, GmailTokenManager(google_settings, db_factory, oauth))
        with pytest.raises(OAuthError, match="reconnect_required"):
            await api.profile_history_id()
    async with db_factory() as session:
        row = await session.scalar(
            select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
        )
        assert row is not None and row.status == "degraded"


@pytest.mark.asyncio
async def test_bounded_initial_sync_maps_metadata_and_commits_shared_checkpoint(
    db_factory, google_settings
) -> None:
    await _seed_connection(db_factory, google_settings)
    listed_limits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "9000"})
        if request.url.path.endswith("/messages"):
            listed_limits.append(request.url.params["maxResults"])
            return httpx.Response(
                200,
                json={"messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]},
            )
        message_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_gmail_metadata_response(message_id))

    source = GmailSyncSource(
        settings=google_settings,
        session_factory=db_factory,
        transport=httpx.MockTransport(handler),
    )
    observations = await source.observe(context=_context())
    assert listed_limits == ["50"]
    assert len(observations) == 1
    assert observations[0].content.history_id == "9000"
    assert len(observations[0].content.messages) == 3
    await ingest_gmail_observations("gmail", observations, _context(), session_factory=db_factory)

    assert await _row_count(db_factory, CanonicalEventRow) == 6
    assert await _row_count(db_factory, OutboxMessageRow) == 6
    async with db_factory() as session:
        checkpoint = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.provider == "gmail",
                ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT,
            )
        )
        assert checkpoint is not None and checkpoint.checkpoint_value == "9000"
        event = await session.scalar(
            select(CanonicalEventRow).where(CanonicalEventRow.event_type == "mail.message.received")
        )
        assert event is not None
        assert set(event.payload) == {
            "message_id",
            "thread_id",
            "sender",
            "subject",
            "received_at",
            "snippet",
            "unread",
            "important",
        }
        encoded = json.dumps(event.payload)
        assert "body" not in event.payload
        assert "access-private" not in encoded and "refresh-token-private" not in encoded


@pytest.mark.asyncio
async def test_incremental_history_maps_new_mail_and_only_meaningful_flag_changes(
    db_factory, google_settings
) -> None:
    await _seed_connection(db_factory, google_settings)
    async with db_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    ProviderCheckpointRow(
                        provider="gmail", checkpoint_key=HISTORY_CHECKPOINT, checkpoint_value="100"
                    ),
                    ProviderCheckpointRow(
                        provider="gmail",
                        checkpoint_key=f"{MESSAGE_STATE_PREFIX}old1",
                        checkpoint_value=json.dumps(
                            {"thread_id": "thread-old", "unread": False, "important": False}
                        ),
                    ),
                    ProviderCheckpointRow(
                        provider="gmail",
                        checkpoint_key=f"{MESSAGE_STATE_PREFIX}stable",
                        checkpoint_value=json.dumps(
                            {"thread_id": "thread-stable", "unread": True, "important": False}
                        ),
                    ),
                ]
            )
            old_message = _metadata("known-delete", "thread-delete", unread=False)
            known_event = CanonicalEvent(
                source="gmail",
                event_type="mail.message.received",
                subject_type="email",
                subject_id=old_message.message_id,
                occurred_at=old_message.received_at,
                observed_at=old_message.received_at,
                version=1,
                dedupe_key=f"gmail:message.received:{old_message.message_id}",
                correlation_id=uuid4(),
                payload={
                    "message_id": old_message.message_id,
                    "thread_id": old_message.thread_id,
                    "sender": old_message.sender,
                    "subject": old_message.subject,
                    "received_at": old_message.received_at.isoformat(),
                    "snippet": old_message.snippet,
                    "unread": old_message.is_unread,
                    "important": old_message.is_important,
                },
            )
            session.add(CanonicalEventRow(**known_event.model_dump()))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/history"):
            assert request.url.params["startHistoryId"] == "100"
            assert set(request.url.params.get_list("historyTypes")) == {
                "messageAdded",
                "messageDeleted",
                "labelAdded",
                "labelRemoved",
            }
            return httpx.Response(
                200,
                json={
                    "historyId": "104",
                    "history": [
                        {"id": "101", "messagesAdded": [{"message": {"id": "new1"}}]},
                        {"id": "102", "labelsAdded": [{"message": {"id": "old1"}}]},
                        {"id": "103", "labelsRemoved": [{"message": {"id": "stable"}}]},
                        {
                            "id": "104",
                            "messagesDeleted": [
                                {
                                    "message": {
                                        "id": "known-delete",
                                        "threadId": "thread-delete",
                                    }
                                }
                            ],
                        },
                    ],
                },
            )
        message_id = request.url.path.rsplit("/", 1)[-1]
        labels = {"new1": ["UNREAD"], "old1": ["UNREAD"], "stable": ["UNREAD"]}[message_id]
        return httpx.Response(200, json=_gmail_metadata_response(message_id, labels=labels))

    source = GmailSyncSource(
        settings=google_settings,
        session_factory=db_factory,
        transport=httpx.MockTransport(handler),
    )
    observations = await source.observe(context=_context())
    batch = observations[0].content
    assert batch.history_id == "104"
    assert [delta.change for delta in batch.messages] == [
        "message_added",
        "labels_changed",
        "labels_changed",
        "message_removed",
    ]
    await ingest_gmail_observations("gmail", observations, _context(), session_factory=db_factory)
    assert await _row_count(db_factory, CanonicalEventRow, event_type="mail.message.received") == 2
    # New message, unread transition, and removal. The irrelevant label change adds no event.
    assert await _row_count(db_factory, CanonicalEventRow, event_type="mail.thread.updated") == 3
    async with db_factory() as session:
        checkpoint = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT
            )
        )
        assert checkpoint is not None and checkpoint.checkpoint_value == "104"


@pytest.mark.asyncio
async def test_checkpoint_rolls_back_when_event_outbox_acceptance_fails(
    db_factory, monkeypatch
) -> None:
    import app.providers.gmail.sync as sync

    async def reject(_session, _event):
        raise RuntimeError("injected ingestion failure")

    monkeypatch.setattr(sync, "persist_event_and_outbox", reject)
    observation = _observation("200", [_metadata()])
    with pytest.raises(RuntimeError, match="injected ingestion failure"):
        await ingest_gmail_observations(
            "gmail", [observation], _context(), session_factory=db_factory
        )
    assert await _row_count(db_factory, CanonicalEventRow) == 0
    assert await _row_count(db_factory, OutboxMessageRow) == 0
    assert await _row_count(db_factory, ProviderCheckpointRow) == 0


@pytest.mark.asyncio
async def test_expired_history_404_runs_bounded_resync_and_deduplicates_known_mail(
    db_factory, google_settings
) -> None:
    await _seed_connection(db_factory, google_settings)
    context = _context()
    original = _observation("10", [_metadata("known1", "thread-known")])
    await ingest_gmail_observations("gmail", [original], context, session_factory=db_factory)
    async with db_factory() as session:
        async with session.begin():
            checkpoint = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT
                )
            )
            assert checkpoint is not None
            checkpoint.checkpoint_value = "1"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/history"):
            assert request.url.params["startHistoryId"] == "1"
            return httpx.Response(404, json={"error": "history expired"})
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "2000"})
        if request.url.path.endswith("/messages"):
            assert request.url.params["maxResults"] == "50"
            return httpx.Response(200, json={"messages": [{"id": "known1"}]})
        return httpx.Response(200, json=_gmail_metadata_response("known1"))

    source = GmailSyncSource(
        settings=google_settings,
        session_factory=db_factory,
        transport=httpx.MockTransport(handler),
    )
    observations = await source.observe(context=_context())
    assert observations[0].content.resynced is True
    assert observations[0].content.history_id == "2000"
    await ingest_gmail_observations("gmail", observations, _context(), session_factory=db_factory)
    assert await _row_count(db_factory, CanonicalEventRow) == 2
    assert await _row_count(db_factory, OutboxMessageRow) == 2
    async with db_factory() as session:
        checkpoint = await session.scalar(
            select(ProviderCheckpointRow).where(
                ProviderCheckpointRow.checkpoint_key == HISTORY_CHECKPOINT
            )
        )
        assert checkpoint is not None and checkpoint.checkpoint_value == "2000"


@pytest.mark.asyncio
async def test_429_honors_retry_after_and_scheduler_backoff_floor(
    google_settings, db_factory
) -> None:
    await _seed_connection(db_factory, google_settings)
    now = datetime.now(UTC)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        api = GmailApiClient(http, GmailTokenManager(google_settings, db_factory, oauth))
        with pytest.raises(RetryAfterError) as caught:
            await api.profile_history_id()
    assert caught.value.retry_after >= now + timedelta(seconds=119)
    delay = next_poll_delay(
        interval=timedelta(seconds=10),
        failure_count=1,
        max_backoff=timedelta(minutes=5),
        jitter_ratio=0,
        random_value=0.5,
        retry_after=caught.value.retry_after,
        now=now,
    )
    assert delay >= timedelta(seconds=119)


@pytest.mark.asyncio
async def test_history_poll_is_bounded_and_checkpoints_last_processed_record(
    db_factory, google_settings
) -> None:
    await _seed_connection(db_factory, google_settings)
    history_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        history_requests.append(request)
        return httpx.Response(
            200,
            json={
                "historyId": "9999",
                "nextPageToken": "more-history",
                "history": [{"id": str(value)} for value in range(101, 151)],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = GoogleOAuth(google_settings, db_factory, http)
        api = GmailApiClient(http, GmailTokenManager(google_settings, db_factory, oauth))
        checkpoint, records = await api.history(start_history_id="100")
    assert len(history_requests) == 1
    assert history_requests[0].url.params["maxResults"] == "50"
    assert len(records) == 50
    assert checkpoint == "150"


@pytest.mark.asyncio
async def test_read_service_validates_limits_and_exposes_no_mutation_methods(
    db_factory, google_settings
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http:
        service = GmailReadOnlyService.create(
            settings=google_settings, session_factory=db_factory, http=http
        )
        with pytest.raises(ValueError, match="limit"):
            await service.get_recent_messages(limit=51)
        with pytest.raises(ValueError, match="limit"):
            await service.get_unread_messages(limit=0)
    methods = {
        name
        for name in dir(GmailReadOnlyService)
        if not name.startswith("_") and callable(getattr(GmailReadOnlyService, name))
    }
    assert methods == {
        "create",
        "get_recent_messages",
        "get_unread_messages",
        "get_message_metadata",
        "get_thread_metadata",
        "get_message_body_for_explicit_request",
    }


@pytest.mark.asyncio
async def test_body_method_is_explicit_ephemeral_and_redacted(db_factory, google_settings) -> None:
    import base64

    await _seed_connection(db_factory, google_settings)
    body_text = "explicitly requested private message text"
    body_data = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg1",
                "threadId": "thread1",
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": body_data},
                    "headers": [],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = GmailReadOnlyService.create(
            settings=google_settings, session_factory=db_factory, http=http
        )
        result = await service.get_message_body_for_explicit_request("msg1")
    assert result.text == body_text
    assert body_text not in repr(result)
    assert calls[0].method == "GET"
    assert calls[0].url.params["format"] == "full"
    assert await _row_count(db_factory, CanonicalEventRow) == 0


def test_safe_representations_and_event_mapping_exclude_body_and_tokens() -> None:
    metadata = _metadata()
    body = GmailMessageBody("msg1", "thread1", "private body text access-private")
    assert "private body text" not in repr(body)
    assert "access-private" not in repr(body)
    event = CanonicalEvent(
        source="gmail",
        event_type="mail.message.received",
        subject_type="email",
        subject_id=metadata.message_id,
        occurred_at=metadata.received_at,
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key="gmail:message.received:msg1",
        correlation_id=uuid4(),
        payload={
            "message_id": metadata.message_id,
            "thread_id": metadata.thread_id,
            "sender": metadata.sender,
            "subject": metadata.subject,
            "received_at": metadata.received_at.isoformat(),
            "snippet": metadata.snippet,
            "unread": metadata.is_unread,
            "important": metadata.is_important,
        },
    )
    encoded = event.model_dump_json()
    assert "access-private" not in encoded
    assert "private body text" not in encoded
    assert "body" not in event.payload
    assert re.fullmatch(r"gmail:message\.received:msg1", event.dedupe_key)


def test_uvicorn_access_log_redacts_oauth_callback_query_values() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "server.py",
        1,
        '%s - "%s %s HTTP/1.1" %d',
        (
            "127.0.0.1",
            "GET",
            "/api/v1/providers/gmail/oauth/callback?code=one-time-code&state=csrf-state",
            200,
        ),
        None,
    )
    assert OAuthAccessLogRedactionFilter().filter(record)
    message = record.getMessage()
    assert "one-time-code" not in message
    assert "csrf-state" not in message
    assert "[REDACTED]" in message


@pytest.mark.asyncio
async def test_mail_canonical_event_reaches_timeline_without_match_state(
    db_factory, monkeypatch
) -> None:
    import app.projections.projector as projector

    event = CanonicalEvent(
        source="gmail",
        event_type="mail.message.received",
        subject_type="email",
        subject_id="message-7",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key="gmail:message.received:message-7",
        correlation_id=uuid4(),
        payload={"message_id": "message-7", "thread_id": "thread-7", "subject": "Hello"},
    )
    async with db_factory() as session:
        async with session.begin():
            session.add(CanonicalEventRow(**event.model_dump()))
    published: list[dict[str, object]] = []

    async def publish(message: dict[str, object]) -> None:
        published.append(message)

    monkeypatch.setattr(projector, "SessionFactory", db_factory)
    monkeypatch.setattr(projector.realtime, "publish", publish)
    assert await projector.process_canonical_event(event)
    assert await _row_count(db_factory, PulseTimelineRow, event_id=event.event_id) == 1
    assert await _row_count(db_factory, ConsumerProcessedEventRow, event_id=event.event_id) == 1
    assert published[0]["event_type"] == "mail.message.received"
    assert "state" not in published[0]


def _gmail_metadata_response(
    message_id: str, *, labels: list[str] | None = None
) -> dict[str, object]:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "internalDate": "1789226400000",
        "snippet": "Safe dashboard preview",
        "payload": {
            "headers": [
                {"name": "From", "value": "A Sender <sender@example.test>"},
                {"name": "Subject", "value": "A subject"},
                {"name": "Date", "value": "Sat, 12 Sep 2026 10:00:00 +0000"},
            ]
        },
    }


def _observation(history_id: str, messages: list[GmailMessageMetadata]):
    from app.providers.observations import Observation

    return Observation[GmailSyncBatch](
        provider_id="gmail",
        external_entity_id="mailbox",
        observed_at=datetime.now(UTC),
        content=GmailSyncBatch(
            history_id=history_id,
            messages=tuple(GmailMessageDelta(metadata=item, change="initial") for item in messages),
        ),
        checkpoint=history_id,
        correlation_id=_context().correlation_id,
    )
