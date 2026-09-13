import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from uuid6 import uuid7

from app.core.config import Settings
from app.providers.base import PollContext
from app.providers.weather.client import (
    CURRENT_FIELDS,
    DAILY_FIELDS,
    OpenMeteoClient,
    OpenMeteoError,
    normalize_weather_code,
    parse_forecast,
)
from app.providers.weather.service import WeatherStateService
from app.providers.weather.source import (
    WeatherPollSource,
    build_weather_source,
    meaningful_change_reasons,
)
from app.providers.weather.storage import build_weather_event

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


def _payload(
    *,
    temperature: float = 70,
    apparent: float = 69,
    code: int = 2,
    precipitation: float = 0,
    wind: float = 5,
    high: float = 75,
    low: float = 60,
    probability: float = 20,
) -> dict[str, object]:
    return {
        "current": {
            "time": "2026-09-12T12:00",
            "temperature_2m": temperature,
            "apparent_temperature": apparent,
            "weather_code": code,
            "precipitation": precipitation,
            "wind_speed_10m": wind,
        },
        "daily": {
            "time": ["2026-09-12"],
            "temperature_2m_max": [high],
            "temperature_2m_min": [low],
            "precipitation_probability_max": [probability],
        },
    }


def _settings(**kwargs: object) -> Settings:
    return Settings(
        _env_file=None,
        weather_latitude=12.345,
        weather_longitude=-67.89,
        weather_timezone="Etc/UTC",
        **kwargs,
    )


def test_open_meteo_response_parses_to_clean_fahrenheit_dto() -> None:
    result = parse_forecast(_payload(), timezone="Etc/UTC", observed_at=NOW)
    assert result.temperature_f == 70
    assert result.apparent_temperature_f == 69
    assert result.precipitation_in == 0
    assert result.wind_speed_mph == 5
    assert result.high_f == 75 and result.low_f == 60
    assert result.precipitation_probability_max_pct == 20
    assert result.category == "cloudy"
    assert result.description == "Partly cloudy"
    assert result.observed_at == datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    assert "latitude" not in result.model_dump()
    assert "longitude" not in result.model_dump()


@pytest.mark.parametrize(
    ("code", "category"),
    [
        (0, "clear"),
        (2, "cloudy"),
        (45, "fog"),
        (55, "drizzle"),
        (63, "rain"),
        (73, "snow"),
        (95, "thunderstorm"),
        (999, "unknown"),
    ],
)
def test_weather_code_presentation_normalization(code: int, category: str) -> None:
    assert normalize_weather_code(code)[0] == category


@pytest.mark.asyncio
async def test_open_meteo_client_requests_current_and_daily_fields_without_api_key() -> None:
    requested: list[str] = []

    async def transport(url: str, timeout: float):
        requested.append(url)
        return 200, {}, json.dumps(_payload()).encode()

    client = OpenMeteoClient(transport=transport)
    result = await client.forecast(latitude=12.345, longitude=-67.89, timezone="Etc/UTC")
    assert isinstance(result, dict)
    query = parse_qs(urlparse(requested[0]).query)
    assert urlparse(requested[0]).path == "/v1/forecast"
    assert query["current"] == [",".join(CURRENT_FIELDS)]
    assert query["daily"] == [",".join(DAILY_FIELDS)]
    assert query["temperature_unit"] == ["fahrenheit"]
    assert query["wind_speed_unit"] == ["mph"]
    assert query["precipitation_unit"] == ["inch"]
    assert "apikey" not in query and "api_key" not in query
    configured = _settings()
    assert configured.provider_configuration()["weather"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "headers", "code"),
    [
        (429, {"Retry-After": "30"}, "weather_rate_limited"),
        (500, {}, "weather_server_error"),
        (503, {}, "weather_server_error"),
    ],
)
async def test_open_meteo_rate_limit_and_server_errors_are_normalized(
    status: int, headers: dict[str, str], code: str
) -> None:
    async def transport(_url: str, _timeout: float):
        return status, headers, b"{}"

    client = OpenMeteoClient(transport=transport)
    with pytest.raises(OpenMeteoError) as error:
        await client.forecast(latitude=1, longitude=2, timezone="UTC")
    assert error.value.detail_code == code
    assert (error.value.retry_after is not None) is (status == 429)


def test_missing_location_disables_provider_and_has_no_baked_in_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.weather_latitude is None and settings.weather_longitude is None
    assert settings.weather_timezone is None
    assert build_weather_source(settings) is None
    assert settings.provider_configuration()["weather"] is False
    assert build_weather_source(_settings()) is not None


@pytest.mark.asyncio
async def test_weather_poll_schedule_and_unchanged_state_suppression() -> None:
    settings = _settings()
    state: dict[str, str] = {}
    calls: list[tuple[str, ...]] = []

    async def read_checkpoints(keys):
        calls.append(tuple(keys))
        return {key: state[key] for key in keys if key in state}

    class MutableForecastClient:
        current = _payload()

        async def forecast(self, **_kwargs):
            return self.current

    client = MutableForecastClient()
    source = WeatherPollSource(
        settings,
        client=client,  # type: ignore[arg-type]
        checkpoint_reader=read_checkpoints,
        clock=lambda: NOW,
    )
    assert source.schedule.interval == timedelta(minutes=20)
    assert source.schedule.timeout == timedelta(seconds=20)
    context = PollContext(correlation_id=uuid7(), scheduled_at=NOW)
    first = await source.observe(context=context)
    assert len(first) == 1 and first[0].content.meaningful_change is True
    assert first[0].content.change_reasons == ("initial_observation",)
    event = build_weather_event(
        first[0].content, observed_at=first[0].observed_at, correlation_id=uuid7()
    )
    assert event is not None and event.event_type == "weather.conditions.updated"
    state["event_baseline"] = first[0].content.current.model_dump_json()

    client.current = _payload(
        temperature=71, apparent=70, precipitation=0.01, wind=7, high=76, low=61, probability=25
    )
    unchanged = await source.observe(context=context)
    assert unchanged[0].content.meaningful_change is False
    assert unchanged[0].content.change_reasons == ()
    assert (
        build_weather_event(
            unchanged[0].content,
            observed_at=unchanged[0].observed_at,
            correlation_id=uuid7(),
        )
        is None
    )

    client.current = _payload(
        temperature=73, apparent=69, precipitation=0.01, wind=7, high=76, low=61, probability=25
    )
    changed = await source.observe(context=context)
    assert changed[0].content.meaningful_change is True
    assert "temperature_changed" in changed[0].content.change_reasons
    assert calls == [("event_baseline",)] * 3


def test_meaningful_change_policy_and_weather_health_freshness() -> None:
    baseline = parse_forecast(_payload(), timezone="Etc/UTC", observed_at=NOW)
    slight = parse_forecast(
        _payload(temperature=71, apparent=70, wind=8, high=76, low=61, probability=25),
        timezone="Etc/UTC",
        observed_at=NOW,
    )
    assert meaningful_change_reasons(baseline, slight) == []
    notable = parse_forecast(
        _payload(temperature=72, code=61, wind=11, probability=35),
        timezone="Etc/UTC",
        observed_at=NOW,
    )
    reasons = meaningful_change_reasons(baseline, notable)
    assert "condition_category_changed" in reasons
    assert "temperature_changed" in reasons
    assert "wind_changed" in reasons
    assert "precipitation_probability_changed" in reasons

    service = WeatherStateService()
    configured = _settings()
    assert service.health_snapshot(configured)["freshness"] == "unknown"
    service.update(baseline, fetched_at=NOW)
    fresh = service.health_snapshot(configured, now=NOW + timedelta(minutes=30))
    stale = service.health_snapshot(configured, now=NOW + timedelta(minutes=50))
    assert fresh["status"] == "healthy" and fresh["freshness"] == "fresh"
    assert stale["status"] == "degraded" and stale["freshness"] == "stale"
    assert stale["detail_code"] == "poll_stale"
