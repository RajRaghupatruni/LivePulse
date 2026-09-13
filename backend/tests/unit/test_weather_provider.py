import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
from app.providers.weather.geocoding import WeatherGeocoder
from app.providers.weather.location import WeatherLocation, local_location_id
from app.providers.weather.locations import (
    bootstrap_configured_location,
    get_weather_location_state,
    select_weather_location,
)
from app.providers.weather.service import WeatherStateService
from app.providers.weather.source import (
    WeatherPollSource,
    build_weather_source,
    meaningful_change_reasons,
)
from app.providers.weather.storage import build_weather_event
from app.storage.models import Base

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


def _location(
    city: str = "Celina",
    region: str | None = "Texas",
    country: str = "United States",
    latitude: float = 33.3246,
    longitude: float = -96.7844,
    timezone: str = "America/Chicago",
) -> WeatherLocation:
    return WeatherLocation(
        id=local_location_id(
            city=city,
            region=region,
            country=country,
            latitude=latitude,
            longitude=longitude,
        ),
        display_name=", ".join(part for part in (city, region, country) if part),
        city=city,
        region=region,
        country=country,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
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
    source = build_weather_source(settings)
    assert source is not None and source.configured is False
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

    async def read_location():
        return _location()

    class MutableForecastClient:
        current = _payload()

        async def forecast(self, **_kwargs):
            return self.current

    client = MutableForecastClient()
    source = WeatherPollSource(
        settings,
        client=client,  # type: ignore[arg-type]
        checkpoint_reader=read_checkpoints,
        location_reader=read_location,
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
    baseline_key = f"event_baseline:{first[0].content.location.id}"
    state[baseline_key] = first[0].content.current.model_dump_json()
    state["has_observation"] = "1"

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
    assert calls == [(baseline_key, "has_observation")] * 3


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


def test_weather_snapshot_restore_tracks_the_selected_location() -> None:
    service = WeatherStateService()
    location_a, location_b = uuid7(), uuid7()
    newer = parse_forecast(
        _payload(temperature=80), timezone="Etc/UTC", observed_at=NOW + timedelta(minutes=10)
    )
    older = parse_forecast(_payload(temperature=55), timezone="Europe/London", observed_at=NOW)

    service.restore(newer, fetched_at=newer.observed_at, location_id=location_a)
    service.restore(older, fetched_at=older.observed_at, location_id=location_b)

    assert service.current(location_id=location_a) is None
    assert service.current(location_id=location_b) == older
    assert service.health_snapshot(
        Settings(_env_file=None), configured=True, now=NOW + timedelta(minutes=1)
    )["last_success_at"] == older.observed_at.isoformat()


@pytest.mark.asyncio
async def test_open_meteo_geocoder_normalizes_celina_and_bounds_cached_search() -> None:
    calls: list[str] = []

    async def transport(url: str, _timeout: float, _headers):
        calls.append(url)
        return (
            200,
            json.dumps(
                {
                    "results": [
                        {
                            "id": 123,
                            "name": "Celina",
                            "latitude": 33.3246,
                            "longitude": -96.7844,
                            "timezone": "America/Chicago",
                            "country": "United States",
                            "admin1": "Texas",
                        }
                    ]
                }
            ).encode(),
        )

    geocoder = WeatherGeocoder(transport=transport, clock=lambda: 100.0)
    result = await geocoder.search("Celina, TX")
    again = await geocoder.search(" celina, tx ")
    assert result == again and len(calls) == 1
    location = result[0]
    assert location.display_name == "Celina, Texas, United States"
    assert location.city == "Celina" and location.region == "Texas"
    assert location.country == "United States"
    assert location.latitude == pytest.approx(33.3246)
    assert location.longitude == pytest.approx(-96.7844)
    assert location.timezone == "America/Chicago"
    assert "id" not in location.model_dump(exclude={"id"})
    params = parse_qs(urlparse(calls[0]).query)
    assert params["count"] == ["6"] and params["name"] == ["Celina, TX"]


@pytest.mark.asyncio
async def test_selected_location_and_five_recents_persist_in_database() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        for index in range(7):
            await select_weather_location(
                _location(
                    city=f"City {index}",
                    region=None,
                    latitude=10 + index,
                    longitude=20 + index,
                    timezone="Etc/UTC",
                ),
                now=NOW + timedelta(minutes=index),
                sessions=sessions,
            )
        state = await get_weather_location_state(
            Settings(_env_file=None), sessions=sessions
        )
        selected = state["selected"]
        recent = state["recent"]
        assert isinstance(selected, WeatherLocation)
        assert selected.city == "City 6"
        assert selected.timezone == "Etc/UTC"
        assert len(recent) == 5
        assert recent[0].id == selected.id
        assert {item.city for item in recent} == {
            "City 2", "City 3", "City 4", "City 5", "City 6"
        }
        # A new read after the writes reconstructs the selection as a backend restart would.
        reloaded = await get_weather_location_state(
            Settings(_env_file=None), sessions=sessions
        )
        assert reloaded["selected"].id == selected.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_configured_coordinate_bootstrap_uses_reverse_geocoding_name_and_timezone() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def transport(_url: str, _timeout: float, _headers):
        return (
            200,
            json.dumps(
                {
                    "address": {
                        "city": "Celina",
                        "state": "Texas",
                        "country": "United States",
                    }
                }
            ).encode(),
        )

    try:
        location = await bootstrap_configured_location(
            _settings(),
            sessions=sessions,
            geocoder=WeatherGeocoder(transport=transport),
        )
        assert location is not None
        assert location.display_name == "Celina, Texas, United States"
        assert location.timezone == "Etc/UTC"
        state = await get_weather_location_state(Settings(_env_file=None), sessions=sessions)
        assert state["selected"].id == location.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_switching_selected_location_changes_weather_poll_coordinates() -> None:
    first, second = _location(), _location(
        city="London",
        region="England",
        country="United Kingdom",
        latitude=51.5072,
        longitude=-0.1276,
        timezone="Europe/London",
    )
    active = first
    requests: list[tuple[float, float, str]] = []

    async def read_location():
        return active

    async def read_checkpoints(_keys):
        return {"has_observation": "1"}

    class RecordingClient:
        async def forecast(self, *, latitude, longitude, timezone):
            requests.append((latitude, longitude, timezone))
            return _payload()

    source = WeatherPollSource(
        Settings(_env_file=None),
        client=RecordingClient(),  # type: ignore[arg-type]
        checkpoint_reader=read_checkpoints,
        location_reader=read_location,
        clock=lambda: NOW,
    )
    context = PollContext(correlation_id=uuid7(), scheduled_at=NOW)
    first_observation = await source.observe(context=context)
    active = second
    second_observation = await source.observe(context=context)
    assert requests == [
        (first.latitude, first.longitude, first.timezone),
        (second.latitude, second.longitude, second.timezone),
    ]
    assert first_observation[0].content.location.display_name.startswith("Celina")
    assert second_observation[0].content.location.display_name.startswith("London")
    assert second_observation[0].content.meaningful_change is False
