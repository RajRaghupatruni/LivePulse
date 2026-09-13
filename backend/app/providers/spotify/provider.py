"""Composition root for Spotify OAuth, playback polling, health and commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.providers.commands import CommandRequest, CommandResult
from app.providers.spotify.auth import (
    ConnectionStore,
    OAuthStateStore,
    SpotifyOAuthService,
    SqlAlchemySpotifyConnectionStore,
    is_spotify_configured,
)
from app.providers.spotify.client import SpotifyApiClient
from app.providers.spotify.commands import SpotifyCommandTarget
from app.providers.spotify.health import SpotifyHealthRegistry, SpotifyHealthSnapshot
from app.providers.spotify.playback import (
    SpotifyAvailableDevice,
    SpotifyEventSink,
    SpotifyPlaybackView,
    SpotifyPollSource,
    parse_available_device,
)
from app.storage.database import SessionFactory


class SpotifyConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = "spotify"
    connected: bool
    status: str
    health: SpotifyHealthSnapshot


class SpotifyProvider:
    provider_id = "spotify"

    def __init__(
        self,
        *,
        settings_getter: Callable[[], Settings] = get_settings,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
        connection_store: ConnectionStore | None = None,
        state_store: OAuthStateStore | None = None,
        health: SpotifyHealthRegistry | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings_getter = settings_getter
        self.connection_store = connection_store or SqlAlchemySpotifyConnectionStore(
            session_factory, settings_getter=settings_getter, clock=clock
        )
        self.state_store = state_store or OAuthStateStore(clock=clock)
        self.health = health or SpotifyHealthRegistry(clock=clock)
        self.oauth = SpotifyOAuthService(
            self.connection_store,
            settings_getter=settings_getter,
            http_client=http_client,
            clock=clock,
            on_reconnect_required=self._report_reconnect_required,
        )
        self.client = SpotifyApiClient(
            self.connection_store,
            self.oauth,
            self.health,
            settings_getter=settings_getter,
            http_client=http_client,
            clock=clock,
        )
        self.poll_source = SpotifyPollSource(
            self.client,
            self.health,
            settings_getter=settings_getter,
            clock=clock,
        )
        self.command_target = SpotifyCommandTarget(self.client)
        self.event_sink = SpotifyEventSink(session_factory=session_factory)

    async def connection_status(self) -> SpotifyConnectionStatus:
        info = await self.connection_store.connection_info()
        configured = self._configured()
        if not info.connected and info.status != "degraded":
            self.health.report(
                "disconnected",
                "not_connected" if configured else "configuration_missing",
                configured=configured,
            )
        health = self.health.snapshot(
            settings=self.settings_getter(),
            connection_status=info.status,
            connected_at=info.connected_at,
        )
        return SpotifyConnectionStatus(
            connected=info.connected and health.connected,
            status=health.status,
            health=health,
        )

    async def disconnect(self) -> SpotifyConnectionStatus:
        await self.connection_store.disconnect()
        self.poll_source.reset()
        self.health.report(
            "disconnected",
            "local_connection_removed",
            configured=self._configured(),
        )
        return await self.connection_status()

    async def execute(self, request: CommandRequest) -> CommandResult:
        return await self.command_target.execute(request)

    def playback(self) -> SpotifyPlaybackView:
        return self.poll_source.playback_view()

    async def available_devices(self) -> list[SpotifyAvailableDevice]:
        devices = await self.client.get_available_devices()
        return [parse_available_device(device) for device in devices]

    def _report_reconnect_required(self) -> None:
        self.health.report(
            "authorization_expired",
            "authorization_expired",
            configured=self._configured(),
        )

    def _configured(self) -> bool:
        return is_spotify_configured(self.settings_getter())
