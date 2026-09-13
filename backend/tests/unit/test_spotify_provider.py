from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import ValidationError
from uuid6 import uuid7

from app.core.config import Settings
from app.core.errors import LivePulseError, livepulse_error_handler
from app.domain.events import CanonicalEvent
from app.projections import projector
from app.providers.base import PollContext
from app.providers.commands import CommandRequest
from app.providers.credentials import CredentialCipher, EncryptedCredentials
from app.providers.scheduler import RetryAfterError
from app.providers.spotify.auth import (
    OAuthStateStore,
    SpotifyOAuthService,
    SpotifyTokens,
)
from app.providers.spotify.client import (
    SpotifyApiClient,
    SpotifyAuthenticationRequired,
    SpotifyRateLimited,
)
from app.providers.spotify.commands import SpotifyCommandTarget
from app.providers.spotify.health import SpotifyHealthRegistry
from app.providers.spotify.playback import (
    NO_DEVICE_INTERVAL,
    PAUSED_INTERVAL,
    PLAYING_INTERVAL,
    SpotifyEventSink,
    SpotifyPollSource,
    parse_available_device,
    parse_playback_snapshot,
)
from app.providers.spotify.provider import SpotifyProvider
from app.providers.spotify.router import create_spotify_router
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    MatchStateRow,
    PulseTimelineRow,
)

REDIRECT_URI = "http://127.0.0.1:8000/api/v1/providers/spotify/oauth/callback"
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        spotify_client_id="spotify-client-id",
        spotify_client_secret="spotify-client-secret",
        spotify_redirect_uri=REDIRECT_URI,
        credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MemoryConnectionStore:
    """Test store that exercises the same encrypted credential wrapper as SQL storage."""

    def __init__(self, key: str) -> None:
        self._cipher = CredentialCipher(key)
        self._encrypted: EncryptedCredentials | None = None
        self._status = "disconnected"
        self._connected_at: datetime | None = None

    async def load_tokens(self) -> SpotifyTokens | None:
        if self._encrypted is None or self._status != "connected":
            return None
        return SpotifyTokens.from_json(self._cipher.decrypt(self._encrypted))

    async def save_tokens(self, tokens: SpotifyTokens) -> None:
        self._encrypted = self._cipher.encrypt(tokens.to_json())
        self._status = "connected"
        self._connected_at = self._connected_at or NOW

    async def mark_reconnect_required(self) -> None:
        self._encrypted = None
        self._status = "degraded"

    async def disconnect(self) -> None:
        self._encrypted = None
        self._status = "disconnected"
        self._connected_at = None

    async def connection_info(self):
        from app.providers.spotify.auth import SpotifyConnectionInfo

        return SpotifyConnectionInfo(
            connected=self._status == "connected" and self._encrypted is not None,
            status=self._status,
            connected_at=self._connected_at,
        )

    @property
    def encrypted_blob(self) -> str | None:
        return self._encrypted.token if self._encrypted else None


def make_store(settings: Settings) -> MemoryConnectionStore:
    assert settings.credential_encryption_key is not None
    return MemoryConnectionStore(settings.credential_encryption_key.get_secret_value())


def token(
    access: str = "access-secret",
    refresh: str = "refresh-secret",
    *,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> SpotifyTokens:
    return SpotifyTokens(
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at,
        scopes=("user-read-playback-state", "user-modify-playback-state"),
    )


def api_payload(
    *,
    item_id: str = "track-1",
    playing: bool = True,
    device_id: str = "device-1",
    context_uri: str = "spotify:playlist:playlist-1",
    timestamp: int = 1_789_200_000_000,
    progress_ms: int = 1500,
) -> dict[str, object]:
    return {
        "is_playing": playing,
        "currently_playing_type": "track",
        "timestamp": timestamp,
        "progress_ms": progress_ms,
        "shuffle_state": True,
        "repeat_state": "context",
        "context": {"type": "playlist", "uri": context_uri},
        "device": {
            "id": device_id,
            "name": f"Device {device_id}",
            "type": "computer",
            "volume_percent": 63,
        },
        "item": {
            "id": item_id,
            "uri": f"spotify:track:{item_id}",
            "name": f"Song {item_id}",
            "type": "track",
            "duration_ms": 210_000,
            "artists": [{"name": "Artist One"}, {"name": "Artist Two"}],
            "album": {
                "name": "Album One",
                "images": [
                    {"url": "https://image.example/small.jpg", "width": 64, "height": 64},
                    {"url": "https://image.example/large.jpg", "width": 640, "height": 640},
                ],
            },
        },
    }


@pytest.mark.asyncio
async def test_oauth_state_is_random_expiring_one_use_and_callback_rejects_mismatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = MutableClock()
    states = OAuthStateStore(ttl=timedelta(seconds=5), clock=clock)
    first = states.create()
    second = states.create()
    assert first != second and len(first) >= 40
    assert not states.consume("attacker-state")
    assert not states.consume("é" * 64)
    assert states.consume(first)
    assert not states.consume(first)

    expiring = states.create()
    clock.value += timedelta(seconds=5)
    assert not states.consume(expiring)

    settings = make_settings()
    store = make_store(settings)

    token_request_assertions: list[bool] = []

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        expected_auth = base64.b64encode(b"spotify-client-id:spotify-client-secret").decode("ascii")
        assert request.headers["Authorization"] == f"Basic {expected_auth}"
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["authorization-code-secret"]
        assert form["redirect_uri"] == [REDIRECT_URI]
        token_request_assertions.append(True)
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
                "scope": "user-read-playback-state user-modify-playback-state",
            },
        )

    logged_callback_queries: list[bytes] = []

    class AccessLogScopeProbe:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            async def capture(message):
                if message["type"] == "http.response.start" and scope.get("path", "").endswith(
                    "/oauth/callback"
                ):
                    logged_callback_queries.append(scope.get("query_string", b""))
                await send(message)

            await self.app(scope, receive, capture)

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)) as http:
        provider = SpotifyProvider(
            settings_getter=lambda: settings,
            connection_store=store,
            state_store=OAuthStateStore(clock=clock),
            health=SpotifyHealthRegistry(),
            http_client=http,
            clock=clock,
        )
        app = FastAPI()
        app.add_exception_handler(LivePulseError, livepulse_error_handler)
        app.add_middleware(AccessLogScopeProbe)
        app.include_router(create_spotify_router(provider))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as browser:
            start = await browser.get(
                "/api/v1/providers/spotify/oauth/start", follow_redirects=False
            )
            assert start.status_code == 302
            authorization = parse_qs(urlsplit(start.headers["location"]).query)
            assert authorization["scope"] == ["user-read-playback-state user-modify-playback-state"]
            assert authorization["redirect_uri"] == [REDIRECT_URI]
            valid_state = authorization["state"][0]

            mismatch = await browser.get(
                "/api/v1/providers/spotify/oauth/callback",
                params={"state": "wrong-state", "code": "authorization-code-secret"},
            )
            assert mismatch.status_code == 400
            assert "state_mismatch" in mismatch.text
            assert "authorization-code-secret" not in mismatch.text

            callback = await browser.get(
                "/api/v1/providers/spotify/oauth/callback",
                params={"state": valid_state, "code": "authorization-code-secret"},
            )
            assert callback.status_code == 200
            assert callback.json() == {"provider": "spotify", "connected": True}
            assert token_request_assertions == [True]
            assert "access-secret" not in callback.text
            assert "refresh-secret" not in callback.text
            assert "authorization-code-secret" not in caplog.text

            assert store.encrypted_blob is not None
            assert "access-secret" not in store.encrypted_blob
            assert "refresh-secret" not in store.encrypted_blob
            assert "access-secret" not in repr(await store.load_tokens())
            assert "refresh-secret" not in repr(await store.load_tokens())

            status = await browser.get("/api/v1/providers/spotify/connection")
            assert status.json()["connected"] is True
            assert "access-secret" not in status.text and "refresh-secret" not in status.text
            assert "scopes" not in status.text
            assert logged_callback_queries == [b"", b""]

            disconnected = await browser.delete("/api/v1/providers/spotify/connection")
            assert disconnected.status_code == 200
            assert disconnected.json()["connected"] is False
            assert disconnected.json()["status"] == "disconnected"
            assert await store.load_tokens() is None


def test_oauth_redirect_uri_requires_exact_callback_path_and_secure_origin() -> None:
    from app.providers.spotify.auth import SpotifyOAuthError

    settings = make_settings()
    store = make_store(settings)
    service = SpotifyOAuthService(store, settings_getter=lambda: settings)
    assert "redirect_uri=" in service.authorization_url("state-value")

    insecure = Settings(
        _env_file=None,
        spotify_client_id="id",
        spotify_client_secret="secret",
        spotify_redirect_uri="http://localhost:8000/api/v1/providers/spotify/oauth/callback",
        credential_encryption_key=settings.credential_encryption_key,
    )
    with pytest.raises(SpotifyOAuthError, match="redirect_uri_invalid"):
        SpotifyOAuthService(store, settings_getter=lambda: insecure).authorization_url(
            "state-value"
        )


@pytest.mark.asyncio
async def test_expired_access_token_refreshes_and_preserves_omitted_refresh_token() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token(expires_at=NOW - timedelta(seconds=1)))
    requests: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == "https://accounts.spotify.com/api/token":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["refresh-secret"]
            return httpx.Response(
                200, json={"access_token": "new-access-secret", "expires_in": 3600}
            )
        assert request.headers["Authorization"] == "Bearer new-access-secret"
        return httpx.Response(200, json=api_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        health = SpotifyHealthRegistry(clock=lambda: NOW)
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            health,
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        result = await client.get_current_playback()

    assert result is not None
    persisted = await store.load_tokens()
    assert persisted is not None
    assert persisted.access_token == "new-access-secret"
    assert persisted.refresh_token == "refresh-secret"
    assert len(requests) == 2
    assert "new-access-secret" not in (store.encrypted_blob or "")


@pytest.mark.asyncio
async def test_401_refreshes_once_then_retries_player_request() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token())
    api_calls = 0
    refresh_calls = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls, refresh_calls
        if request.url == "https://accounts.spotify.com/api/token":
            refresh_calls += 1
            return httpx.Response(200, json={"access_token": "refreshed", "expires_in": 3600})
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer refreshed"
        return httpx.Response(200, json=api_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            SpotifyHealthRegistry(),
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        assert await client.get_current_playback() is not None
    assert api_calls == 2
    assert refresh_calls == 1
    assert (await store.load_tokens()).refresh_token == "refresh-secret"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_invalid_grant_clears_tokens_and_reports_reconnect_required() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token(expires_at=NOW - timedelta(seconds=1)))

    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        provider = SpotifyProvider(
            settings_getter=lambda: settings,
            connection_store=store,
            health=SpotifyHealthRegistry(clock=lambda: NOW),
            http_client=http,
            clock=lambda: NOW,
        )
        with pytest.raises(SpotifyAuthenticationRequired, match="authorization_expired"):
            await provider.client.get_current_playback()
        status = await provider.connection_status()

    assert await store.load_tokens() is None
    assert status.status == "reconnect_required"
    assert status.health.detail_code == "authorization_expired"


@pytest.mark.asyncio
async def test_concurrent_expired_requests_share_a_single_refresh() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token(expires_at=NOW - timedelta(seconds=1)))
    refresh_calls = 0
    playback_calls = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_calls, playback_calls
        if str(request.url) == "https://accounts.spotify.com/api/token":
            refresh_calls += 1
            return httpx.Response(
                200, json={"access_token": "one-refreshed-token", "expires_in": 3600}
            )
        playback_calls += 1
        assert request.headers["Authorization"] == "Bearer one-refreshed-token"
        return httpx.Response(200, json=api_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            SpotifyHealthRegistry(clock=lambda: NOW),
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        results = await asyncio.gather(client.get_current_playback(), client.get_current_playback())

    assert all(result is not None for result in results)
    assert refresh_calls == 1
    assert playback_calls == 2


@pytest.mark.asyncio
async def test_no_playback_204_and_available_devices_use_read_scope_endpoint() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token())
    paths: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/devices"):
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {
                            "id": "speaker-1",
                            "name": "Kitchen speaker",
                            "type": "speaker",
                            "is_active": True,
                            "is_restricted": False,
                            "volume_percent": 45,
                            "supports_volume": True,
                        }
                    ]
                },
            )
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            SpotifyHealthRegistry(clock=lambda: NOW),
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        assert await client.get_current_playback() is None
        devices = await client.get_available_devices()

    assert paths == ["/v1/me/player", "/v1/me/player/devices"]
    assert devices[0]["id"] == "speaker-1"


def test_playback_dto_parses_track_device_context_and_artwork() -> None:
    state = parse_playback_snapshot(api_payload())
    assert state.is_playing is True
    assert (state.item_type, state.item_id, state.item_uri, state.item_name) == (
        "track",
        "track-1",
        "spotify:track:track-1",
        "Song track-1",
    )
    assert state.artists == ("Artist One", "Artist Two")
    assert state.album_name == "Album One"
    assert state.artwork_url == "https://image.example/large.jpg"
    assert (state.progress_ms, state.duration_ms) == (1500, 210_000)
    assert (state.device_id, state.device_name, state.device_type, state.volume_percent) == (
        "device-1",
        "Device device-1",
        "computer",
        63,
    )
    assert (state.shuffle, state.repeat, state.context_uri, state.context_type) == (
        True,
        "context",
        "spotify:playlist:playlist-1",
        "playlist",
    )


def test_available_devices_dto_parses_transferable_device_metadata() -> None:
    device = parse_available_device(
        {
            "id": "speaker-1",
            "name": "Kitchen speaker",
            "type": "speaker",
            "is_active": False,
            "is_restricted": False,
            "volume_percent": 40,
            "supports_volume": True,
        }
    )
    assert device.id == "speaker-1"
    assert device.name == "Kitchen speaker"
    assert device.type == "speaker"
    assert device.volume_percent == 40 and device.supports_volume is True


class FakePlaybackClient:
    def __init__(self, values: list[dict[str, object] | None]) -> None:
        self.values = list(values)

    async def get_current_playback(self):
        return self.values.pop(0)


def poll_context() -> PollContext:
    return PollContext(correlation_id=uuid7(), scheduled_at=NOW)


@pytest.mark.asyncio
async def test_identical_poll_is_suppressed_and_pause_resume_track_device_context_change() -> None:
    settings = make_settings()
    values = [
        api_payload(),
        api_payload(progress_ms=5500),  # progress alone is not a timeline event
        api_payload(playing=False),
        api_payload(playing=True, progress_ms=9000),
        api_payload(item_id="track-2", device_id="device-2", context_uri="spotify:album:album-2"),
    ]
    client = FakePlaybackClient(values)
    source = SpotifyPollSource(
        client,  # type: ignore[arg-type]
        SpotifyHealthRegistry(),
        settings_getter=lambda: settings,
        clock=lambda: NOW,
    )
    assert source.cadence(context=poll_context()) == NO_DEVICE_INTERVAL
    initial = await source.observe(context=poll_context())
    assert initial[0].content.event_types == (
        "spotify.playback.started",
        "spotify.track.changed",
    )
    assert source.cadence(context=poll_context()) == PLAYING_INTERVAL
    assert await source.observe(context=poll_context()) == ()

    paused = await source.observe(context=poll_context())
    assert paused[0].content.event_types == ("spotify.playback.paused",)
    assert source.cadence(context=poll_context()) == PAUSED_INTERVAL
    resumed = await source.observe(context=poll_context())
    assert resumed[0].content.event_types == ("spotify.playback.resumed",)
    changed = await source.observe(context=poll_context())
    assert set(changed[0].content.event_types) == {
        "spotify.track.changed",
        "spotify.device.changed",
        "spotify.context.changed",
    }
    assert source.playback_view().playback.item_id == "track-2"


@pytest.mark.asyncio
async def test_429_retry_after_is_preserved_for_shared_scheduler() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token())

    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "25"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        health = SpotifyHealthRegistry(clock=lambda: NOW)
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            health,
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        with pytest.raises(SpotifyRateLimited) as limited:
            await client.get_current_playback()
        assert limited.value.retry_after == NOW + timedelta(seconds=25)

        source = SpotifyPollSource(
            client,
            health,
            settings_getter=lambda: settings,
            clock=lambda: NOW,
        )
        with pytest.raises(RetryAfterError) as scheduled:
            await source.observe(context=poll_context())
    assert scheduled.value.retry_after == NOW + timedelta(seconds=25)
    assert (
        health.snapshot(
            settings=settings,
            connection_status="connected",
            connected_at=NOW,
        ).status
        == "rate_limited"
    )


@pytest.mark.asyncio
async def test_all_commands_map_to_fixed_spotify_endpoints_and_validate_arguments() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token())
    captured: list[tuple[str, str, dict[str, list[str]], bytes]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        captured.append(
            (
                request.method,
                request.url.path,
                {key: list(value) for key, value in parse_qs(request.url.query.decode()).items()},
                request.content,
            )
        )
        return httpx.Response(204)

    requests = [
        (CommandRequest(command="spotify.play"), "PUT", "/v1/me/player/play"),
        (CommandRequest(command="spotify.pause"), "PUT", "/v1/me/player/pause"),
        (CommandRequest(command="spotify.next"), "POST", "/v1/me/player/next"),
        (CommandRequest(command="spotify.previous"), "POST", "/v1/me/player/previous"),
        (
            CommandRequest(command="spotify.seek", arguments={"position_seconds": 35}),
            "PUT",
            "/v1/me/player/seek",
        ),
        (
            CommandRequest(command="spotify.volume", arguments={"volume_percent": 75}),
            "PUT",
            "/v1/me/player/volume",
        ),
        (
            CommandRequest(command="spotify.transfer_device", arguments={"device_id": "device-2"}),
            "PUT",
            "/v1/me/player",
        ),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            SpotifyHealthRegistry(),
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        target = SpotifyCommandTarget(client)
        for request, _, _ in requests:
            result = await target.execute(request)
            assert result.success is True
            assert result.provider == "spotify"
    assert [(method, path) for method, path, _, _ in captured] == [
        (method, path) for _, method, path in requests
    ]
    assert captured[4][2] == {"position_ms": ["35000"]}
    assert captured[5][2] == {"volume_percent": ["75"]}
    assert captured[6][3] == b'{"device_ids":["device-2"]}'

    for arguments in [
        {"position_seconds": -1},
        {"position_seconds": 86_401},
        {"volume_percent": 101},
        {"device_id": ""},
    ]:
        command = (
            "spotify.seek"
            if "position_seconds" in arguments
            else "spotify.volume"
            if "volume_percent" in arguments
            else "spotify.transfer_device"
        )
        with pytest.raises(ValidationError):
            CommandRequest(command=command, arguments=arguments)  # type: ignore[arg-type]

    whitespace_device = CommandRequest(
        command="spotify.transfer_device", arguments={"device_id": "   "}
    )
    result = await target.execute(whitespace_device)
    assert result.success is False and result.error_code == "invalid_state"


@pytest.mark.asyncio
async def test_403_premium_failure_and_disconnected_health_are_safe() -> None:
    settings = make_settings()
    store = make_store(settings)
    await store.save_tokens(token())

    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Premium is required"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        health = SpotifyHealthRegistry()
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            health,
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        result = await SpotifyCommandTarget(client).execute(CommandRequest(command="spotify.pause"))
    assert result.success is False
    assert result.error_code == "provider_error"
    assert "Premium" in result.message
    assert "Premium is required" not in result.message

    def not_found(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "NO_ACTIVE_DEVICE"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(not_found)) as http:
        oauth = SpotifyOAuthService(
            store, settings_getter=lambda: settings, http_client=http, clock=lambda: NOW
        )
        client = SpotifyApiClient(
            store,
            oauth,
            SpotifyHealthRegistry(clock=lambda: NOW),
            settings_getter=lambda: settings,
            http_client=http,
            clock=lambda: NOW,
        )
        missing_device = await SpotifyCommandTarget(client).execute(
            CommandRequest(command="spotify.next")
        )
    assert missing_device.success is False
    assert missing_device.error_code == "invalid_state"

    disconnected = SpotifyProvider(
        settings_getter=lambda: settings,
        connection_store=make_store(settings),
        health=SpotifyHealthRegistry(),
    )
    status = await disconnected.connection_status()
    assert status.status == "disconnected"
    assert status.connected is False
    assert status.health.configured is True
    assert status.health.detail_code == "not_connected"


@pytest.mark.asyncio
async def test_event_sink_uses_canonical_event_outbox_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    source = SpotifyPollSource(
        FakePlaybackClient([api_payload()]),  # type: ignore[arg-type]
        SpotifyHealthRegistry(),
        settings_getter=lambda: settings,
        clock=lambda: NOW,
    )
    observations = await source.observe(context=poll_context())
    persisted = []

    class FakeSession:
        def begin(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    @asynccontextmanager
    async def session_factory():
        yield FakeSession()

    async def persist(_session, event):
        persisted.append(event)
        return True

    monkeypatch.setattr("app.providers.spotify.playback.persist_event_and_outbox", persist)
    sink = SpotifyEventSink(session_factory=session_factory)  # type: ignore[arg-type]
    await sink.handle("spotify", observations, poll_context())

    assert [event.event_type for event in persisted] == [
        "spotify.playback.started",
        "spotify.track.changed",
    ]
    assert all(
        event.source == "spotify" and event.subject_type == "spotify_playback"
        for event in persisted
    )
    assert all(
        event.subject_id == "current" and event.dedupe_key.startswith("spotify:")
        for event in persisted
    )
    assert all(event.version == 1 for event in persisted)
    assert all(event.occurred_at <= event.observed_at for event in persisted)


@pytest.mark.asyncio
async def test_spotify_canonical_event_projects_to_timeline_without_touching_match_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = CanonicalEvent(
        source="spotify",
        event_type="spotify.track.changed",
        subject_type="spotify_playback",
        subject_id="current",
        occurred_at=NOW,
        observed_at=NOW,
        version=1,
        dedupe_key="spotify:track.changed:deterministic-test",
        correlation_id=uuid7(),
        payload={"item_uri": "spotify:track:track-1", "item_name": "Song track-1"},
    )
    persisted_event = CanonicalEventRow(**event.model_dump())
    timelines: list[PulseTimelineRow] = []
    processed: set[tuple[str, object]] = set()
    notifications: list[dict[str, object]] = []

    class FakeSession:
        def begin(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, model, identity):
            if model is CanonicalEventRow:
                return persisted_event if identity == event.event_id else None
            if model is ConsumerProcessedEventRow:
                return True if identity in processed else None
            if model is MatchStateRow:
                raise AssertionError("Spotify events must not write football match state")
            return None

        def add(self, row) -> None:
            if isinstance(row, ConsumerProcessedEventRow):
                processed.add((row.consumer_name, row.event_id))
            elif isinstance(row, PulseTimelineRow):
                timelines.append(row)

        async def flush(self) -> None:
            for timeline in timelines:
                if timeline.cursor is None:
                    timeline.cursor = len(timelines)

    session = FakeSession()

    @asynccontextmanager
    async def session_factory():
        yield session

    async def publish(notification: dict[str, object]) -> None:
        notifications.append(notification)

    monkeypatch.setattr(projector, "SessionFactory", session_factory)
    monkeypatch.setattr(projector.realtime, "publish", publish)

    assert await projector.process_canonical_event(event) is True
    assert await projector.process_canonical_event(event) is False
    assert len(timelines) == 1
    assert len(processed) == 1
    assert notifications[0]["event_type"] == "spotify.track.changed"
    assert notifications[0]["subject_id"] == "current"
    assert "state" not in notifications[0]
