"""Spotify playback DTOs, adaptive polling, change detection and canonical events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.events.repository import persist_event_and_outbox
from app.providers.base import PollContext, PollSchedule
from app.providers.observations import Observation
from app.providers.scheduler import RetryAfterError
from app.providers.spotify.auth import is_spotify_configured
from app.providers.spotify.client import SpotifyApiClient, SpotifyApiError, SpotifyRateLimited
from app.providers.spotify.health import SpotifyHealthRegistry
from app.storage.database import SessionFactory

SpotifyEventType = Literal[
    "spotify.playback.started",
    "spotify.playback.paused",
    "spotify.playback.resumed",
    "spotify.track.changed",
    "spotify.device.changed",
    "spotify.context.changed",
]

PLAYING_INTERVAL = timedelta(seconds=5)
PAUSED_INTERVAL = timedelta(seconds=20)
NO_DEVICE_INTERVAL = timedelta(seconds=60)


class SpotifyPlaybackSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    is_playing: bool
    item_type: str | None = Field(default=None, max_length=40)
    item_id: str | None = Field(default=None, max_length=200)
    item_uri: str | None = Field(default=None, max_length=300)
    item_name: str | None = Field(default=None, max_length=500)
    artists: tuple[str, ...] = ()
    album_name: str | None = Field(default=None, max_length=500)
    show_name: str | None = Field(default=None, max_length=500)
    artwork_url: str | None = Field(default=None, max_length=2048)
    progress_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    device_id: str | None = Field(default=None, max_length=200)
    device_name: str | None = Field(default=None, max_length=300)
    device_type: str | None = Field(default=None, max_length=100)
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    shuffle: bool | None = None
    repeat: str | None = Field(default=None, max_length=40)
    context_uri: str | None = Field(default=None, max_length=300)
    context_type: str | None = Field(default=None, max_length=100)
    timestamp_ms: int | None = Field(default=None, ge=0)

    @property
    def item_identity(self) -> str | None:
        return self.item_uri or self.item_id


class SpotifyPlaybackChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: SpotifyPlaybackSnapshot
    event_types: tuple[SpotifyEventType, ...] = Field(min_length=1)


class SpotifyPlaybackView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["spotify"] = "spotify"
    playback: SpotifyPlaybackSnapshot | None
    observed_at: datetime | None = None
    freshness_seconds: float | None = Field(default=None, ge=0)


class SpotifyAvailableDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str | None = Field(default=None, max_length=200)
    name: str = Field(max_length=300)
    type: str = Field(max_length=100)
    is_active: bool
    is_restricted: bool
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    supports_volume: bool


class SpotifyPollSource:
    provider_id = "spotify"
    schedule = PollSchedule(
        interval=PAUSED_INTERVAL,
        timeout=timedelta(seconds=15),
        max_backoff=timedelta(minutes=5),
        jitter_ratio=0.1,
    )

    def __init__(
        self,
        client: SpotifyApiClient,
        health: SpotifyHealthRegistry,
        *,
        settings_getter: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._health = health
        self._settings_getter = settings_getter
        self._clock = clock
        self._previous: SpotifyPlaybackSnapshot | None = None
        self._current: SpotifyPlaybackSnapshot | None = None
        self._observed_at: datetime | None = None

    def reset(self) -> None:
        self._previous = None
        self._current = None
        self._observed_at = None

    def cadence(self, *, context: PollContext) -> timedelta:
        del context
        if self._current is None:
            return NO_DEVICE_INTERVAL
        return PLAYING_INTERVAL if self._current.is_playing else PAUSED_INTERVAL

    def playback_view(self) -> SpotifyPlaybackView:
        now = _utc(self._clock())
        freshness = (
            max(0.0, (now - self._observed_at).total_seconds()) if self._observed_at else None
        )
        return SpotifyPlaybackView(
            playback=self._current,
            observed_at=self._observed_at,
            freshness_seconds=freshness,
        )

    async def observe(
        self, *, context: PollContext
    ) -> Sequence[Observation[SpotifyPlaybackChange]]:
        try:
            raw = await self._client.get_current_playback()
        except SpotifyRateLimited as exc:
            raise RetryAfterError(exc.retry_after, "rate_limited") from exc
        except SpotifyApiError as exc:
            if exc.detail_code not in {
                "not_authenticated",
                "authorization_expired",
                "reconnect_required",
            }:
                configured = is_spotify_configured(self._settings_getter())
                self._health.report("degraded", exc.detail_code, configured=configured)
            raise

        now = _utc(self._clock())
        previous = self._previous
        current = parse_playback_snapshot(raw) if raw is not None else None
        self._previous = current
        self._current = current
        self._observed_at = now
        configured = is_spotify_configured(self._settings_getter())
        self._health.report(
            "healthy",
            "no_active_device" if current is None else "playback_observed",
            configured=configured,
            observed=True,
        )
        if current is None:
            return ()
        event_types = spotify_event_changes(previous, current)
        if not event_types:
            return ()
        change = SpotifyPlaybackChange(snapshot=current, event_types=event_types)
        return (
            Observation[SpotifyPlaybackChange](
                provider_id=self.provider_id,
                external_entity_id=current.item_identity or "current",
                observed_at=now,
                content=change,
                provider_version=(
                    str(current.timestamp_ms) if current.timestamp_ms is not None else None
                ),
                correlation_id=context.correlation_id,
            ),
        )


class SpotifyEventSink:
    """Normalize changed provider observations into the existing event/outbox transaction."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    ) -> None:
        self._session_factory = session_factory

    async def handle(
        self,
        provider_id: str,
        observations: Sequence[Observation[BaseModel]],
        context: PollContext,
    ) -> None:
        if provider_id != "spotify":
            raise ValueError("Spotify event sink only accepts Spotify observations")
        async with self._session_factory() as session:
            async with session.begin():
                for observation in observations:
                    if not isinstance(observation.content, SpotifyPlaybackChange):
                        raise TypeError("Spotify observations must contain playback changes")
                    for event_type in observation.content.event_types:
                        event = normalize_spotify_event(
                            observation,
                            event_type,
                            correlation_id=observation.correlation_id or context.correlation_id,
                        )
                        await persist_event_and_outbox(session, event)


def parse_playback_snapshot(payload: dict[str, Any]) -> SpotifyPlaybackSnapshot:
    item = payload.get("item") if isinstance(payload.get("item"), dict) else None
    device = payload.get("device") if isinstance(payload.get("device"), dict) else None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else None
    album = item.get("album") if item and isinstance(item.get("album"), dict) else None
    show = item.get("show") if item and isinstance(item.get("show"), dict) else None
    images = (
        album.get("images")
        if album and isinstance(album.get("images"), list)
        else item.get("images", [])
        if item
        else []
    )
    artwork_url = _largest_image_url(images)
    artists = tuple(
        artist["name"]
        for artist in (item.get("artists", []) if item else [])
        if isinstance(artist, dict) and isinstance(artist.get("name"), str) and artist["name"]
    )
    return SpotifyPlaybackSnapshot(
        is_playing=payload.get("is_playing") is True,
        item_type=_text(payload.get("currently_playing_type"))
        or (_text(item.get("type")) if item else None),
        item_id=_text(item.get("id")) if item else None,
        item_uri=_text(item.get("uri")) if item else None,
        item_name=_text(item.get("name")) if item else None,
        artists=artists,
        album_name=_text(album.get("name")) if album else None,
        show_name=_text(show.get("name")) if show else None,
        artwork_url=artwork_url,
        progress_ms=_nonnegative_int(payload.get("progress_ms")),
        duration_ms=_nonnegative_int(item.get("duration_ms")) if item else None,
        device_id=_text(device.get("id")) if device else None,
        device_name=_text(device.get("name")) if device else None,
        device_type=_text(device.get("type")) if device else None,
        volume_percent=_bounded_int(device.get("volume_percent"), 0, 100) if device else None,
        shuffle=payload.get("shuffle_state")
        if isinstance(payload.get("shuffle_state"), bool)
        else None,
        repeat=_text(payload.get("repeat_state")),
        context_uri=_text(context.get("uri")) if context else None,
        context_type=_text(context.get("type")) if context else None,
        timestamp_ms=_nonnegative_int(payload.get("timestamp")),
    )


def parse_available_device(payload: dict[str, Any]) -> SpotifyAvailableDevice:
    return SpotifyAvailableDevice(
        id=_text(payload.get("id")),
        name=_text(payload.get("name")) or "Spotify device",
        type=_text(payload.get("type")) or "unknown",
        is_active=payload.get("is_active") is True,
        is_restricted=payload.get("is_restricted") is True,
        volume_percent=_bounded_int(payload.get("volume_percent"), 0, 100),
        supports_volume=payload.get("supports_volume") is True,
    )


def spotify_event_changes(
    previous: SpotifyPlaybackSnapshot | None,
    current: SpotifyPlaybackSnapshot,
) -> tuple[SpotifyEventType, ...]:
    events: list[SpotifyEventType] = []
    if current.is_playing and (previous is None or not previous.is_playing):
        if previous is not None and previous.item_identity == current.item_identity:
            events.append("spotify.playback.resumed")
        else:
            events.append("spotify.playback.started")
    elif previous is not None and previous.is_playing and not current.is_playing:
        events.append("spotify.playback.paused")

    if current.item_identity and (
        previous is None or previous.item_identity != current.item_identity
    ):
        events.append("spotify.track.changed")
    if previous is not None and _device_identity(previous) != _device_identity(current):
        events.append("spotify.device.changed")
    if previous is not None and _context_identity(previous) != _context_identity(current):
        events.append("spotify.context.changed")
    return tuple(events)


def normalize_spotify_event(
    observation: Observation[SpotifyPlaybackChange],
    event_type: SpotifyEventType,
    *,
    correlation_id: UUID | None = None,
) -> CanonicalEvent:
    snapshot = observation.content.snapshot
    payload = _event_payload(event_type, snapshot)
    provider_version = observation.provider_version or ""
    fingerprint = hashlib.sha256(
        json.dumps(
            {"event_type": event_type, "provider_version": provider_version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:40]
    occurred_at = (
        datetime.fromtimestamp(snapshot.timestamp_ms / 1000, UTC)
        if snapshot.timestamp_ms is not None
        else observation.observed_at
    )
    return CanonicalEvent(
        source="spotify",
        event_type=event_type,
        subject_type="spotify_playback",
        subject_id="current",
        occurred_at=occurred_at,
        observed_at=observation.observed_at,
        # Spotify timestamps are millisecond-scale values and exceed the
        # canonical PostgreSQL INTEGER range. Spotify events are timeline-only;
        # event identity/deduplication uses the provider timestamp and payload.
        version=1,
        dedupe_key=f"spotify:{event_type}:{fingerprint}",
        correlation_id=correlation_id or observation.correlation_id or uuid7(),
        payload=payload,
    )


def _event_payload(
    event_type: SpotifyEventType, snapshot: SpotifyPlaybackSnapshot
) -> dict[str, Any]:
    if event_type in {
        "spotify.playback.started",
        "spotify.playback.paused",
        "spotify.playback.resumed",
    }:
        return {
            "item_uri": snapshot.item_uri,
            "item_name": snapshot.item_name,
            "artists": list(snapshot.artists),
            "is_playing": snapshot.is_playing,
            "device_id": snapshot.device_id,
            "device_name": snapshot.device_name,
            "context_uri": snapshot.context_uri,
        }
    if event_type == "spotify.track.changed":
        return {
            "item_type": snapshot.item_type,
            "item_id": snapshot.item_id,
            "item_uri": snapshot.item_uri,
            "item_name": snapshot.item_name,
            "artists": list(snapshot.artists),
            "album_name": snapshot.album_name,
            "show_name": snapshot.show_name,
            "artwork_url": snapshot.artwork_url,
            "duration_ms": snapshot.duration_ms,
        }
    if event_type == "spotify.device.changed":
        return {
            "device_id": snapshot.device_id,
            "device_name": snapshot.device_name,
            "device_type": snapshot.device_type,
        }
    return {"context_uri": snapshot.context_uri, "context_type": snapshot.context_type}


def _device_identity(snapshot: SpotifyPlaybackSnapshot) -> tuple[str | None, ...]:
    return snapshot.device_id, snapshot.device_name, snapshot.device_type


def _context_identity(snapshot: SpotifyPlaybackSnapshot) -> tuple[str | None, ...]:
    return snapshot.context_uri, snapshot.context_type


def _largest_image_url(images: object) -> str | None:
    if not isinstance(images, list):
        return None
    candidates = [image for image in images if isinstance(image, dict) and _text(image.get("url"))]
    if not candidates:
        return None
    image = max(
        candidates,
        key=lambda value: (
            (_nonnegative_int(value.get("width")) or 0)
            * (_nonnegative_int(value.get("height")) or 0)
        ),
    )
    return _text(image.get("url"))


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _bounded_int(value: object, minimum: int, maximum: int) -> int | None:
    parsed = _nonnegative_int(value)
    return parsed if parsed is not None and minimum <= parsed <= maximum else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
