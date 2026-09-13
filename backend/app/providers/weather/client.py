"""Open-Meteo HTTP adapter and provider DTO parsing, private to the weather package."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "weather_code",
    "precipitation",
    "wind_speed_10m",
)
DAILY_FIELDS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
)
ResponseTransport = Callable[[str, float], Awaitable[tuple[int, Mapping[str, str], bytes]]]


class OpenMeteoError(RuntimeError):
    def __init__(
        self, status_code: int, detail_code: str, retry_after: datetime | None = None
    ) -> None:
        self.status_code = status_code
        self.detail_code = detail_code
        self.retry_after = retry_after
        super().__init__(detail_code)


class _RawCurrent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: str
    temperature_2m: float
    apparent_temperature: float
    weather_code: int = Field(alias="weather_code")
    precipitation: float
    wind_speed_10m: float


class _RawDaily(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: list[str]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_probability_max: list[float | None] = Field(default_factory=list)


class _RawForecast(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current: _RawCurrent
    daily: _RawDaily


class WeatherConditions(BaseModel):
    """Normalized current and concise daily context; no coordinates or raw DTO fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_at: datetime
    local_time: str
    timezone: str
    temperature_f: float
    apparent_temperature_f: float
    weather_code: int
    category: str
    description: str
    precipitation_in: float
    wind_speed_mph: float
    high_f: float
    low_f: float
    precipitation_probability_max_pct: int | None = None


def normalize_weather_code(code: int) -> tuple[str, str]:
    if code == 0:
        return "clear", "Clear"
    if code in {1, 2, 3}:
        return "cloudy", {1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast"}[code]
    if code in {45, 48}:
        return "fog", "Fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle", "Drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain", "Rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow", "Snow"
    if code in {95, 96, 99}:
        return "thunderstorm", "Thunderstorm"
    return "unknown", "Conditions unavailable"


def parse_forecast(payload: object, *, timezone: str, observed_at: datetime) -> WeatherConditions:
    """Convert a vendor response to the package's normalized dashboard DTO."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    forecast = _RawForecast.model_validate(payload)
    zone = ZoneInfo(timezone)
    local = datetime.fromisoformat(forecast.current.time)
    if local.tzinfo is None:
        local = local.replace(tzinfo=zone)
    local = local.astimezone(zone)
    if (
        not forecast.daily.time
        or not forecast.daily.temperature_2m_max
        or not forecast.daily.temperature_2m_min
    ):
        raise ValueError("Open-Meteo response has no daily temperature context")
    probability = (
        forecast.daily.precipitation_probability_max[0]
        if forecast.daily.precipitation_probability_max
        else None
    )
    category, description = normalize_weather_code(forecast.current.weather_code)
    return WeatherConditions(
        observed_at=local.astimezone(UTC),
        local_time=local.isoformat(),
        timezone=timezone,
        temperature_f=forecast.current.temperature_2m,
        apparent_temperature_f=forecast.current.apparent_temperature,
        weather_code=forecast.current.weather_code,
        category=category,
        description=description,
        precipitation_in=forecast.current.precipitation,
        wind_speed_mph=forecast.current.wind_speed_10m,
        high_f=forecast.daily.temperature_2m_max[0],
        low_f=forecast.daily.temperature_2m_min[0],
        precipitation_probability_max_pct=round(probability) if probability is not None else None,
    )


class OpenMeteoClient:
    def __init__(self, *, transport: ResponseTransport | None = None, timeout: float = 15) -> None:
        self._transport = transport or _urlopen_transport
        self._timeout = timeout

    async def forecast(self, *, latitude: float, longitude: float, timezone: str) -> object:
        params = {
            "latitude": str(latitude),
            "longitude": str(longitude),
            "timezone": timezone,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "forecast_days": "1",
            "current": ",".join(CURRENT_FIELDS),
            "daily": ",".join(DAILY_FIELDS),
        }
        url = f"{OPEN_METEO_ENDPOINT}?{urlencode(params)}"
        try:
            status, headers, body = await self._transport(url, self._timeout)
        except (TimeoutError, URLError, OSError) as exc:
            raise OpenMeteoError(0, "weather_network_error") from exc
        if status == 429:
            retry_after = _retry_time(headers)
            raise OpenMeteoError(status, "weather_rate_limited", retry_after)
        if status >= 500:
            raise OpenMeteoError(status, "weather_server_error")
        if not 200 <= status < 300:
            raise OpenMeteoError(status, "weather_api_error")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise OpenMeteoError(status, "weather_invalid_response") from exc


def _retry_time(headers: Mapping[str, str]) -> datetime | None:
    values = {key.casefold(): value for key, value in headers.items()}
    retry = values.get("retry-after")
    if not retry:
        return None
    try:
        from datetime import timedelta

        return datetime.now(UTC) + timedelta(seconds=max(0, int(retry)))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(retry)
            return parsed.astimezone(UTC) if parsed.tzinfo else None
        except (TypeError, ValueError, OverflowError):
            return None


async def _urlopen_transport(url: str, timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    def execute() -> tuple[int, Mapping[str, str], bytes]:
        request = Request(
            url, headers={"Accept": "application/json", "User-Agent": "LivePulse/1.0"}
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    return await asyncio.to_thread(execute)
