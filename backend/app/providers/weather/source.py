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
from app.providers.weather.service import weather_configured, weather_state
from app.providers.weather.storage import weather_checkpoints

CheckpointReader = Callable[[Sequence[str]], Awaitable[dict[str, str]]]


class WeatherObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not weather_configured(settings):
            raise ValueError("weather polling requires coordinates and timezone")
        self._latitude = settings.weather_latitude
        self._longitude = settings.weather_longitude
        self._timezone = settings.weather_timezone or ""
        self._client = client or OpenMeteoClient()
        self._checkpoint_reader = checkpoint_reader
        self._clock = clock

    def cadence(self, *, context: PollContext) -> timedelta:
        return self.schedule.interval

    async def observe(self, *, context: PollContext) -> Sequence[Observation[BaseModel]]:
        observed_at = self._clock().astimezone(UTC)
        try:
            raw = await self._client.forecast(
                latitude=self._latitude, longitude=self._longitude, timezone=self._timezone
            )
            current = parse_forecast(raw, timezone=self._timezone, observed_at=observed_at)
            saved = await self._checkpoint_reader(("event_baseline",))
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
            WeatherConditions.model_validate_json(saved["event_baseline"])
            if saved.get("event_baseline")
            else None
        )
        reasons = meaningful_change_reasons(baseline, current)
        sample = WeatherObservation(
            current=current,
            meaningful_change=bool(reasons),
            change_reasons=tuple(reasons),
            dedupe_key=_dedupe_key(baseline, current),
        )
        return (
            Observation[WeatherObservation](
                provider_id="weather",
                external_entity_id="configured-location",
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
) -> WeatherPollSource | None:
    """Missing location silently disables polling and never adds a baked-in fallback."""
    return WeatherPollSource(settings, **kwargs) if weather_configured(settings) else None


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


def _dedupe_key(baseline: WeatherConditions | None, current: WeatherConditions) -> str:
    content = current.model_dump(exclude={"observed_at", "local_time"})
    stable = json.dumps(content, sort_keys=True, separators=(",", ":"))
    epoch = baseline.observed_at.isoformat() if baseline else "initial"
    return f"weather:{hashlib.sha256(f'{epoch}:{stable}'.encode()).hexdigest()}"
