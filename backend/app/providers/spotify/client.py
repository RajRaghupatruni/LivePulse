"""Async Spotify Web API client with serialized refresh and safe error mapping."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.providers.spotify.auth import (
    ConnectionStore,
    SpotifyOAuthError,
    SpotifyOAuthService,
    SpotifyTokens,
    is_spotify_configured,
)
from app.providers.spotify.health import SpotifyHealthRegistry

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
TOKEN_REFRESH_SKEW = timedelta(seconds=30)


class SpotifyApiError(RuntimeError):
    """Spotify API error containing no provider response body or credential data."""

    def __init__(
        self,
        detail_code: str,
        *,
        status_code: int | None = None,
        retry_after: datetime | None = None,
    ) -> None:
        self.detail_code = detail_code
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(detail_code)


class SpotifyAuthenticationRequired(SpotifyApiError):
    def __init__(self, detail_code: str = "not_authenticated") -> None:
        super().__init__(detail_code, status_code=401)


class SpotifyRateLimited(SpotifyApiError):
    def __init__(self, retry_after: datetime) -> None:
        super().__init__("rate_limited", status_code=429, retry_after=retry_after)


class SpotifyApiClient:
    def __init__(
        self,
        store: ConnectionStore,
        oauth: SpotifyOAuthService,
        health: SpotifyHealthRegistry,
        *,
        settings_getter: Callable[[], Settings] = get_settings,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.oauth = oauth
        self.health = health
        self._settings_getter = settings_getter
        self._http_client = http_client
        self._clock = clock
        self._refresh_lock = asyncio.Lock()

    async def get_current_playback(self) -> dict[str, Any] | None:
        response = await self.request_player(
            "GET", "/me/player", params={"additional_types": "track,episode"}
        )
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise SpotifyApiError("response_invalid", status_code=response.status_code) from exc
        if not isinstance(data, dict):
            raise SpotifyApiError("response_invalid", status_code=response.status_code)
        return data

    async def get_available_devices(self) -> list[dict[str, Any]]:
        response = await self.request_player("GET", "/me/player/devices")
        try:
            data = response.json()
        except ValueError as exc:
            raise SpotifyApiError("response_invalid", status_code=response.status_code) from exc
        if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
            raise SpotifyApiError("response_invalid", status_code=response.status_code)
        return [device for device in data["devices"] if isinstance(device, dict)]

    async def request_player(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        access_token = await self._current_access_token()
        response = await self._send(method, path, access_token, params=params, json_body=json_body)
        if response.status_code == 401:
            access_token = await self._refresh_after_unauthorized(access_token)
            response = await self._send(
                method, path, access_token, params=params, json_body=json_body
            )
            if response.status_code == 401:
                await self.store.mark_reconnect_required()
                self.health.report(
                    "authorization_expired",
                    "authorization_expired",
                    configured=self._configured(),
                )
                raise SpotifyAuthenticationRequired("authorization_expired")
        self._raise_for_response(response)
        self.health.report(
            "healthy",
            "api_request_succeeded",
            configured=self._configured(),
        )
        return response

    async def _current_access_token(self) -> str:
        try:
            tokens = await self.store.load_tokens()
        except Exception as exc:
            if getattr(exc, "detail_code", None) == "stored_credentials_unavailable":
                self.health.report(
                    "reconnect_required",
                    "stored_credentials_unavailable",
                    configured=self._configured(),
                )
                raise SpotifyAuthenticationRequired("reconnect_required") from exc
            raise
        if tokens is None:
            self.health.report("disconnected", "not_connected", configured=self._configured())
            raise SpotifyAuthenticationRequired()
        if tokens.expires_at > self._now() + TOKEN_REFRESH_SKEW:
            return tokens.access_token
        return await self._refresh_if_needed(tokens)

    async def _refresh_after_unauthorized(self, stale_access_token: str) -> str:
        try:
            async with self._refresh_lock:
                current = await self.store.load_tokens()
                if current is None:
                    raise SpotifyAuthenticationRequired("reconnect_required")
                if current.access_token != stale_access_token:
                    if current.expires_at > self._now() + TOKEN_REFRESH_SKEW:
                        return current.access_token
                return (await self.oauth.refresh(current)).access_token
        except SpotifyOAuthError as exc:
            self._raise_oauth_error(exc)

    async def _refresh_if_needed(self, initial: SpotifyTokens) -> str:
        try:
            async with self._refresh_lock:
                current = await self.store.load_tokens()
                if current is None:
                    raise SpotifyAuthenticationRequired("reconnect_required")
                if (
                    current.access_token != initial.access_token
                    and current.expires_at > self._now() + TOKEN_REFRESH_SKEW
                ):
                    return current.access_token
                return (await self.oauth.refresh(current)).access_token
        except SpotifyOAuthError as exc:
            self._raise_oauth_error(exc)

    async def _send(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        params: dict[str, str | int] | None,
        json_body: dict[str, Any] | None,
    ) -> httpx.Response:
        url = f"{SPOTIFY_API_BASE}{path}"
        kwargs: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {access_token}"},
            "params": params,
            "json": json_body,
            "timeout": 10,
        }
        try:
            if self._http_client is not None:
                return await self._http_client.request(method, url, **kwargs)
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise SpotifyApiError("provider_unavailable", status_code=503) from None

    def _raise_for_response(self, response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 429:
            retry_at = parse_retry_after(response.headers.get("Retry-After"), now=self._now())
            self.health.report(
                "rate_limited",
                "rate_limited",
                configured=self._configured(),
                rate_limited_until=retry_at,
            )
            raise SpotifyRateLimited(retry_at)
        if status == 403:
            self.health.report("degraded", "forbidden", configured=self._configured())
            raise SpotifyApiError("forbidden", status_code=status)
        if status == 404:
            raise SpotifyApiError("not_found", status_code=status)
        if status >= 500:
            self.health.report("degraded", "provider_unavailable", configured=self._configured())
            raise SpotifyApiError("provider_unavailable", status_code=status)
        raise SpotifyApiError("provider_error", status_code=status)

    def _handle_oauth_error(self, exc: SpotifyOAuthError) -> None:
        if exc.detail_code == "authorization_expired":
            self.health.report(
                "authorization_expired",
                "authorization_expired",
                configured=self._configured(),
            )
        elif exc.detail_code == "credential_encryption_unavailable":
            self.health.report(
                "reconnect_required",
                exc.detail_code,
                configured=self._configured(),
            )
        else:
            self.health.report(
                "degraded",
                "token_endpoint_unavailable",
                configured=self._configured(),
            )

    def _raise_oauth_error(self, exc: SpotifyOAuthError) -> None:
        self._handle_oauth_error(exc)
        if exc.detail_code == "authorization_expired":
            raise SpotifyAuthenticationRequired(exc.detail_code) from exc
        if exc.detail_code == "configuration_missing":
            raise SpotifyAuthenticationRequired("reconnect_required") from exc
        raise SpotifyApiError("provider_unavailable", status_code=503) from exc

    def _configured(self) -> bool:
        return is_spotify_configured(self._settings_getter())

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware timestamp")
        return now.astimezone(UTC)


def parse_retry_after(value: str | None, *, now: datetime) -> datetime:
    """Parse Spotify's seconds-based Retry-After, accepting standard HTTP-date too."""

    current = now.astimezone(UTC)
    if value:
        try:
            seconds = max(0, int(value.strip()))
            return current + timedelta(seconds=seconds)
        except (ValueError, OverflowError):
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(current, parsed.astimezone(UTC))
            except (TypeError, ValueError, OverflowError):
                pass
    return current + timedelta(seconds=60)
