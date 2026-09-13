"""Provider-independent weather location contracts."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeatherLocation(BaseModel):
    """A normalized, user-selectable place. Vendor geocoding DTOs stop before this model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    display_name: str = Field(min_length=1, max_length=240)
    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=100)
    selected_at: datetime | None = None
    last_used_at: datetime | None = None

    @field_validator("selected_at", "last_used_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("timezone")
    @classmethod
    def valid_iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


def local_location_id(
    *, city: str, region: str | None, country: str, latitude: float, longitude: float
) -> UUID:
    """Create a stable local identity without exposing a geocoder's entity identifier."""

    identity = "|".join(
        (
            city.strip().casefold(),
            (region or "").strip().casefold(),
            country.strip().casefold(),
            f"{latitude:.5f}",
            f"{longitude:.5f}",
        )
    )
    return uuid5(NAMESPACE_URL, f"livepulse:weather-location:{identity}")


def display_name(city: str, region: str | None, country: str) -> str:
    parts: list[str] = []
    for part in (city, region, country):
        value = (part or "").strip()
        if value and all(value.casefold() != item.casefold() for item in parts):
            parts.append(value)
    return ", ".join(parts)
