"""Modular Spotify API router; the main app can register it during integration."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.errors import LivePulseError
from app.providers.commands import CommandRequest, CommandResult
from app.providers.spotify.auth import OAuthStateStore, SpotifyOAuthError
from app.providers.spotify.client import (
    SpotifyApiError,
    SpotifyAuthenticationRequired,
    SpotifyRateLimited,
)
from app.providers.spotify.health import SpotifyHealthSnapshot
from app.providers.spotify.playback import SpotifyAvailableDevice, SpotifyPlaybackView
from app.providers.spotify.provider import SpotifyConnectionStatus, SpotifyProvider


def create_spotify_router(
    provider: SpotifyProvider | None = None,
    *,
    state_store: OAuthStateStore | None = None,
) -> APIRouter:
    """Create a provider-local router, injectable in tests and app integration."""

    instance = provider or SpotifyProvider()
    oauth_state = state_store or instance.state_store
    router = APIRouter(prefix="/api/v1/providers/spotify", tags=["spotify"])

    @router.get("/oauth/start", include_in_schema=True)
    async def start_authorization() -> RedirectResponse:
        state = oauth_state.create()
        try:
            url = instance.oauth.authorization_url(state)
        except SpotifyOAuthError as exc:
            raise LivePulseError(exc.detail_code, "Spotify OAuth is not configured", 503) from None
        return RedirectResponse(url, status_code=302)

    @router.get("/oauth/callback", include_in_schema=True)
    async def authorization_callback(
        request: Request,
        state: str | None = Query(default=None),
        code: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> RedirectResponse:
        # Uvicorn logs the request path when it sends the response. Strip the OAuth query
        # after FastAPI has parsed it so authorization codes never enter access logs.
        request.scope["query_string"] = b""
        if not oauth_state.consume(state):
            raise LivePulseError("state_mismatch", "Spotify authorization state is invalid", 400)
        if error is not None:
            raise LivePulseError(
                "authorization_denied", "Spotify authorization was not granted", 400
            )
        if not code:
            raise LivePulseError(
                "authorization_code_missing", "Spotify did not return an authorization code", 400
            )
        try:
            await instance.oauth.exchange_authorization_code(code)
        except SpotifyOAuthError as exc:
            status_code = (
                503
                if exc.detail_code
                in {
                    "configuration_missing",
                    "credential_encryption_unavailable",
                    "token_endpoint_unavailable",
                }
                else 502
            )
            raise LivePulseError(
                exc.detail_code, "Spotify connection could not be completed", status_code
            ) from None
        instance.health.report(
            "healthy",
            "connected",
            configured=instance._configured(),
        )
        return RedirectResponse("/?spotify=connected", status_code=303)

    @router.get("/connection", response_model=SpotifyConnectionStatus)
    async def connection_status() -> SpotifyConnectionStatus:
        return await instance.connection_status()

    @router.delete("/connection", response_model=SpotifyConnectionStatus)
    async def disconnect() -> SpotifyConnectionStatus:
        """Remove local encrypted credentials and cached playback state."""

        return await instance.disconnect()

    @router.get("/playback", response_model=SpotifyPlaybackView)
    async def current_playback() -> SpotifyPlaybackView:
        return instance.playback()

    @router.get("/devices", response_model=list[SpotifyAvailableDevice])
    async def available_devices() -> list[SpotifyAvailableDevice]:
        try:
            return await instance.available_devices()
        except SpotifyAuthenticationRequired as exc:
            raise LivePulseError(
                exc.detail_code, "Spotify authorization is required", 401
            ) from None
        except SpotifyRateLimited:
            raise LivePulseError("rate_limited", "Spotify is rate limited", 429) from None
        except SpotifyApiError as exc:
            if exc.status_code == 403:
                raise LivePulseError("forbidden", "Spotify denied device access", 403) from None
            if exc.status_code == 404:
                raise LivePulseError("not_found", "Spotify devices are unavailable", 404) from None
            raise LivePulseError(
                "provider_unavailable", "Spotify devices could not be loaded", 503
            ) from None

    @router.post("/commands", response_model=CommandResult)
    async def execute_command(request: CommandRequest) -> CommandResult:
        return await instance.execute(request)

    @router.get("/health", response_model=SpotifyHealthSnapshot)
    async def spotify_health() -> SpotifyHealthSnapshot:
        return (await instance.connection_status()).health

    return router


spotify_provider = SpotifyProvider()
router = create_spotify_router(spotify_provider)

__all__ = ["create_spotify_router", "router", "spotify_provider"]
