"""Spotify-specific, secret-free health with provider-local authorization states."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.providers.spotify.auth import is_spotify_configured
from app.providers.status import provider_health

SpotifyHealthStatus = Literal[
    "disconnected",
    "healthy",
    "degraded",
    "rate_limited",
    "authorization_expired",
    "reconnect_required",
]


class SpotifyHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["spotify"] = "spotify"
    status: SpotifyHealthStatus
    configured: bool
    connected: bool
    detail_code: str = Field(pattern=r"^[a-z0-9_.-]{1,64}$")
    checked_at: datetime
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_observation_at: datetime | None = None
    rate_limited_until: datetime | None = None
    freshness_seconds: float | None = Field(default=None, ge=0)


class SpotifyHealthRegistry:
    """In-process Spotify health; the shared registry receives its common subset."""

    def __init__(self, *, clock=lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._lock = RLock()
        self._status: SpotifyHealthStatus | None = None
        self._detail_code = "not_observed"
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_observation_at: datetime | None = None
        self._rate_limited_until: datetime | None = None

    def report(
        self,
        status: SpotifyHealthStatus,
        detail_code: str,
        *,
        configured: bool,
        observed: bool = False,
        rate_limited_until: datetime | None = None,
    ) -> None:
        now = _utc(self._clock())
        with self._lock:
            self._status = status
            self._detail_code = detail_code
            if status == "healthy":
                self._last_success_at = now
            if status in {
                "degraded",
                "rate_limited",
                "authorization_expired",
                "reconnect_required",
            }:
                self._last_failure_at = now
            if observed:
                self._last_observation_at = now
            self._rate_limited_until = rate_limited_until

        if status == "healthy":
            provider_health.report(
                "spotify",
                "healthy",
                detail_code,
                configured=configured,
                succeeded=True,
                observed=observed,
            )
        elif status == "disconnected":
            provider_health.report("spotify", "disconnected", detail_code, configured=configured)
        else:
            provider_health.report(
                "spotify",
                "degraded",
                detail_code,
                configured=configured,
                failed=True,
                rate_limited_until=rate_limited_until,
            )

    def snapshot(
        self,
        *,
        settings: Settings,
        connection_status: str,
        connected_at: datetime | None,
    ) -> SpotifyHealthSnapshot:
        configured = is_spotify_configured(settings)
        connected = connection_status == "connected"
        now = _utc(self._clock())
        with self._lock:
            status = self._status
            detail_code = self._detail_code
            last_success_at = self._last_success_at
            last_failure_at = self._last_failure_at
            last_observation_at = self._last_observation_at
            rate_limited_until = self._rate_limited_until

        if not configured:
            status, detail_code, connected = "disconnected", "configuration_missing", False
        elif not connected:
            if connection_status == "degraded":
                status, detail_code = "reconnect_required", "authorization_expired"
            elif status not in {"authorization_expired", "reconnect_required"}:
                status, detail_code = "disconnected", "not_connected"
        elif status is None:
            status, detail_code = "degraded", "not_observed"
        elif status in {"authorization_expired", "reconnect_required"}:
            connected = False
        elif status == "rate_limited" and rate_limited_until and rate_limited_until <= now:
            status, detail_code = "degraded", "rate_limit_elapsed"

        freshness_base = last_observation_at or last_success_at or connected_at
        freshness = (
            max(0.0, (now - _utc(freshness_base)).total_seconds()) if freshness_base else None
        )
        return SpotifyHealthSnapshot(
            status=status,
            configured=configured,
            connected=connected,
            detail_code=detail_code,
            checked_at=now,
            last_success_at=last_success_at,
            last_failure_at=last_failure_at,
            last_observation_at=last_observation_at,
            rate_limited_until=rate_limited_until,
            freshness_seconds=freshness,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("health timestamps must be timezone-aware")
    return value.astimezone(UTC)
