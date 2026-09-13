"""Twenty-minute Open-Meteo polling and normalized meaningful-change detection."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.providers.base import PollContext, PollSchedule
from app.providers.observations import Observation
from app.providers.scheduler import RetryAfterError
from app.providers.weather.client import (
    OpenMeteoClient,
    OpenMeteoError,
    WeatherConditions,
    parse_forecast,
)
from app.providers.weather.location import WeatherLocation
from app.providers.weather.locations import weather_location_for_poll
from app.providers.weather.service import weather_configured, weather_state
from app.providers.weather.storage import weather_checkpoints

CheckpointReader = Callable[[Sequence[str]], Awaitable[dict[str, str]]]
LocationReader = Callable[[], Awaitable[WeatherLocation | None]]


class WeatherObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    location: WeatherLocation
    current: WeatherConditions
    meaningful_change: bool
    change_reasons: tuple[str, ...]
    dedupe_key: str


class WeatherPollSource:
    provider_id = "weather"
    schedule = PollSchedule(
        interval=timedelta(minutes=20),
        timeout=timedelta(seconds=20),
        max_backoff=timedelta(hours=2),
        jitter_ratio=0.1,
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: OpenMeteoClient | None = None,
        checkpoint_reader: CheckpointReader = weather_checkpoints,
        location_reader: LocationReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._location_reader = location_reader or (
            lambda: weather_location_for_poll(self._settings)
        )
        self._configured = weather_configured(settings)
        self._client = client or OpenMeteoClient()
        self._checkpoint_reader = checkpoint_reader
        self._clock = clock

    def cadence(self, *, context: PollContext) -> timedelta:
        return self.schedule.interval

    @property
    def configured(self) -> bool:
        return self._configured

    async def observe(self, *, context: PollContext) -> Sequence[Observation[BaseModel]]:
        observed_at = self._clock().astimezone(UTC)
        try:
            location = await self._location_reader()
            self._configured = location is not None
            if location is None:
                return ()
            raw = await self._client.forecast(
                latitude=location.latitude,
                longitude=location.longitude,
                timezone=location.timezone,
            )
            current = parse_forecast(raw, timezone=location.timezone, observed_at=observed_at)
            baseline_key = f"event_baseline:{location.id}"
            saved = await self._checkpoint_reader((baseline_key, "has_observation"))
        except asyncio.CancelledError:
            weather_state.record_failure("weather_poll_cancelled", now=observed_at)
            raise
        except OpenMeteoError as exc:
            weather_state.record_failure(exc.detail_code, now=observed_at)
            if exc.retry_after:
                raise RetryAfterError(exc.retry_after, exc.detail_code) from exc
            raise
        except Exception:
            weather_state.record_failure("weather_poll_failed", now=observed_at)
            raise
        baseline = (
            WeatherConditions.model_validate_json(saved[baseline_key])
            if saved.get(baseline_key)
            else None
        )
        reasons = meaningful_change_reasons(baseline, current)
        if baseline is None and saved.get("has_observation") == "1":
            reasons = []
        sample = WeatherObservation(
            location=location,
            current=current,
            meaningful_change=bool(reasons),
            change_reasons=tuple(reasons),
            dedupe_key=_dedupe_key(str(location.id), baseline, current),
        )
        return (
            Observation[WeatherObservation](
                provider_id="weather",
                external_entity_id=str(location.id),
                observed_at=observed_at,
                content=sample,
                provider_version=current.observed_at.isoformat(),
                checkpoint=current.observed_at.isoformat(),
                correlation_id=context.correlation_id,
            ),
        )


def build_weather_source(
    settings: Settings,
    **kwargs: Any,
) -> WeatherPollSource:
    """Build a dynamic source even before the user has selected a location."""
    return WeatherPollSource(settings, **kwargs)


def meaningful_change_reasons(
    baseline: WeatherConditions | None, current: WeatherConditions
) -> list[str]:
    if baseline is None:
        return ["initial_observation"]
    reasons: list[str] = []
    if baseline.category != current.category:
        reasons.append("condition_category_changed")
    if abs(baseline.temperature_f - current.temperature_f) >= 2:
        reasons.append("temperature_changed")
    if abs(baseline.apparent_temperature_f - current.apparent_temperature_f) >= 2:
        reasons.append("apparent_temperature_changed")
    if abs(baseline.precipitation_in - current.precipitation_in) >= 0.02:
        reasons.append("precipitation_changed")
    if abs(baseline.wind_speed_mph - current.wind_speed_mph) >= 5:
        reasons.append("wind_changed")
    if abs(baseline.high_f - current.high_f) >= 2 or abs(baseline.low_f - current.low_f) >= 2:
        reasons.append("daily_temperature_range_changed")
    prior_probability = baseline.precipitation_probability_max_pct
    next_probability = current.precipitation_probability_max_pct
    if (
        prior_probability is not None
        and next_probability is not None
        and abs(prior_probability - next_probability) >= 10
    ):
        reasons.append("precipitation_probability_changed")
    return reasons


def _dedupe_key(
    location_id: str, baseline: WeatherConditions | None, current: WeatherConditions
) -> str:
    content = current.model_dump(exclude={"observed_at", "local_time"})
    stable = json.dumps(content, sort_keys=True, separators=(",", ":"))
    epoch = baseline.observed_at.isoformat() if baseline else "initial"
    return f"weather:{hashlib.sha256(f'{location_id}:{epoch}:{stable}'.encode()).hexdigest()}"
