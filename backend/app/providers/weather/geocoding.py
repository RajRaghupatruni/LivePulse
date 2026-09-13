"""Open-Meteo place search and one-time reverse lookup for legacy coordinate bootstraps."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from app.providers.weather.location import WeatherLocation, display_name, local_location_id

OPEN_METEO_GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_STREET_MAP_REVERSE_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
GeocodingTransport = Callable[
    [str, float, Mapping[str, str]], Awaitable[tuple[int, bytes]]
]


class GeocodingError(RuntimeError):
    def __init__(self, code: str = "location_search_unavailable") -> None:
        self.detail_code = code
        super().__init__(code)


class _OpenMeteoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    latitude: float
    longitude: float
    timezone: str
    country: str
    admin1: str | None = None


class _OpenMeteoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_OpenMeteoResult] = Field(default_factory=list)


class _NominatimAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city: str | None = None
    town: str | None = None
    village: str | None = None
    municipality: str | None = None
    hamlet: str | None = None
    suburb: str | None = None
    county: str | None = None
    state: str | None = None
    state_district: str | None = None
    region: str | None = None
    country: str


class _NominatimResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    address: _NominatimAddress


class WeatherGeocoder:
    """Small bounded geocoder with a short in-process cache for interactive searches."""

    def __init__(
        self,
        *,
        transport: GeocodingTransport | None = None,
        timeout: float = 8,
        cache_ttl_seconds: int = 600,
        cache_size: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport or _urlopen_transport
        self._timeout = timeout
        self._cache_ttl = cache_ttl_seconds
        self._cache_size = cache_size
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, list[WeatherLocation]]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._reverse_lock = asyncio.Lock()
        self._last_reverse_at = 0.0

    async def search(self, query: str) -> list[WeatherLocation]:
        normalized = query.strip()
        if not 2 <= len(normalized) <= 80:
            return []
        key = normalized.casefold()
        now = self._clock()
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                self._cache.move_to_end(key)
                return list(cached[1])
            if cached:
                del self._cache[key]

        query_params = {
            "name": normalized,
            "count": 6,
            "language": "en",
            "format": "json",
        }
        url = f"{OPEN_METEO_GEOCODING_ENDPOINT}?{urlencode(query_params)}"
        body = await self._request(url, {"Accept": "application/json"})
        try:
            response = _OpenMeteoResponse.model_validate_json(body)
        except ValueError as exc:
            raise GeocodingError("location_search_invalid_response") from exc
        locations = [_normalize_open_meteo(result) for result in response.results]
        async with self._cache_lock:
            self._cache[key] = (self._clock() + self._cache_ttl, locations)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return locations

    async def reverse_configured_coordinates(
        self, *, latitude: float, longitude: float, timezone: str
    ) -> WeatherLocation:
        """Resolve a one-time configured-coordinate fallback; never used for search typing."""

        async with self._reverse_lock:
            wait = 1.0 - (self._clock() - self._last_reverse_at)
            if self._last_reverse_at and wait > 0:
                await asyncio.sleep(wait)
            self._last_reverse_at = self._clock()
            query_params = {
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "addressdetails": 1,
            }
            url = f"{OPEN_STREET_MAP_REVERSE_ENDPOINT}?{urlencode(query_params)}"
            body = await self._request(
                url,
                {
                    "Accept": "application/json",
                    "User-Agent": "LivePulse/0.1.0 (weather coordinate bootstrap)",
                },
            )
        try:
            response = _NominatimResponse.model_validate_json(body)
        except ValueError as exc:
            raise GeocodingError("weather_location_reverse_lookup_failed") from exc
        address = response.address
        city = next(
            (
                value
                for value in (
                    address.city,
                    address.town,
                    address.village,
                    address.municipality,
                    address.hamlet,
                    address.suburb,
                    address.county,
                )
                if value and value.strip()
            ),
            None,
        )
        if city is None:
            raise GeocodingError("weather_location_reverse_lookup_failed")
        region = address.state or address.state_district or address.region
        return WeatherLocation(
            id=local_location_id(
                city=city,
                region=region,
                country=address.country,
                latitude=latitude,
                longitude=longitude,
            ),
            display_name=display_name(city, region, address.country),
            city=city,
            region=region,
            country=address.country,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
        )

    async def _request(self, url: str, headers: Mapping[str, str]) -> bytes:
        try:
            status, body = await self._transport(url, self._timeout, headers)
        except (TimeoutError, URLError, OSError) as exc:
            raise GeocodingError() from exc
        if not 200 <= status < 300:
            raise GeocodingError("location_search_unavailable")
        return body


def _normalize_open_meteo(result: _OpenMeteoResult) -> WeatherLocation:
    city = result.name.strip()
    region = result.admin1.strip() if result.admin1 and result.admin1.strip() else None
    country = result.country.strip()
    return WeatherLocation(
        id=local_location_id(
            city=city,
            region=region,
            country=country,
            latitude=result.latitude,
            longitude=result.longitude,
        ),
        display_name=display_name(city, region, country),
        city=city,
        region=region,
        country=country,
        latitude=result.latitude,
        longitude=result.longitude,
        timezone=result.timezone,
    )


async def _urlopen_transport(
    url: str, timeout: float, headers: Mapping[str, str]
) -> tuple[int, bytes]:
    def execute() -> tuple[int, bytes]:
        request_headers = {"Accept": "application/json", "User-Agent": "LivePulse/0.1.0"}
        request_headers.update(headers)
        request = Request(url, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    return await asyncio.to_thread(execute)


weather_geocoder = WeatherGeocoder()
