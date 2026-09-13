"""Durable selected and recent weather locations."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.providers.weather.geocoding import GeocodingError, WeatherGeocoder, weather_geocoder
from app.providers.weather.location import WeatherLocation, local_location_id
from app.providers.weather.service import weather_configured
from app.storage.database import SessionFactory
from app.storage.models import WeatherLocationRow, WeatherLocationSelectionRow

RECENT_LOCATION_LIMIT = 5
_bootstrap_lock = asyncio.Lock()


async def get_weather_location_state(
    settings: Settings,
    *,
    sessions: async_sessionmaker[AsyncSession] = SessionFactory,
    geocoder: WeatherGeocoder = weather_geocoder,
) -> dict[str, object]:
    selected = await get_selected_weather_location(sessions=sessions)
    if selected is None and weather_configured(settings):
        try:
            selected = await bootstrap_configured_location(
                settings, sessions=sessions, geocoder=geocoder
            )
        except GeocodingError:
            # Location naming is best-effort; an unavailable reverse geocoder must not
            # turn a previously working local application into a startup failure.
            selected = None
    async with sessions() as session:
        rows = await session.scalars(
            select(WeatherLocationRow)
            .order_by(WeatherLocationRow.last_used_at.desc(), WeatherLocationRow.id)
            .limit(RECENT_LOCATION_LIMIT)
        )
        recent = [_to_location(row) for row in rows]
    return {"selected": selected, "recent": recent}


async def get_selected_weather_location(
    *, sessions: async_sessionmaker[AsyncSession] = SessionFactory
) -> WeatherLocation | None:
    async with sessions() as session:
        selection = await session.get(WeatherLocationSelectionRow, 1)
        if selection is None or selection.location_id is None:
            return None
        row = await session.get(WeatherLocationRow, selection.location_id)
        return _to_location(row) if row else None


async def has_selected_weather_location(
    *, sessions: async_sessionmaker[AsyncSession] = SessionFactory
) -> bool:
    return await get_selected_weather_location(sessions=sessions) is not None


async def select_weather_location(
    candidate: WeatherLocation,
    *,
    now: datetime | None = None,
    sessions: async_sessionmaker[AsyncSession] = SessionFactory,
) -> WeatherLocation:
    selected_at = _utc(now or datetime.now(UTC))
    local_id = local_location_id(
        city=candidate.city,
        region=candidate.region,
        country=candidate.country,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
    )
    values = {
        "id": local_id,
        "display_name": candidate.display_name,
        "city": candidate.city,
        "region": candidate.region,
        "country": candidate.country,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "timezone": candidate.timezone,
        "selected_at": selected_at,
        "last_used_at": selected_at,
    }
    async with sessions() as session:
        async with session.begin():
            dialect = session.bind.dialect.name if session.bind is not None else ""
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            location_insert = insert(WeatherLocationRow).values(**values)
            await session.execute(
                location_insert.on_conflict_do_update(
                    index_elements=["id"],
                    set_={key: value for key, value in values.items() if key != "id"},
                )
            )

            selection_values = {
                "singleton_id": 1,
                "location_id": local_id,
                "selected_at": selected_at,
            }
            selection_insert = insert(WeatherLocationSelectionRow).values(**selection_values)
            await session.execute(
                selection_insert.on_conflict_do_update(
                    index_elements=["singleton_id"],
                    set_={"location_id": local_id, "selected_at": selected_at},
                )
            )

            keep_ids = list(
                await session.scalars(
                    select(WeatherLocationRow.id)
                    .order_by(WeatherLocationRow.last_used_at.desc(), WeatherLocationRow.id)
                    .limit(RECENT_LOCATION_LIMIT)
                )
            )
            await session.execute(
                delete(WeatherLocationRow).where(WeatherLocationRow.id.not_in(keep_ids))
            )
    return candidate.model_copy(
        update={"id": local_id, "selected_at": selected_at, "last_used_at": selected_at}
    )


async def bootstrap_configured_location(
    settings: Settings,
    *,
    sessions: async_sessionmaker[AsyncSession] = SessionFactory,
    geocoder: WeatherGeocoder = weather_geocoder,
) -> WeatherLocation | None:
    async with _bootstrap_lock:
        existing = await get_selected_weather_location(sessions=sessions)
        if existing is not None or not weather_configured(settings):
            return existing
        assert settings.weather_latitude is not None
        assert settings.weather_longitude is not None
        assert settings.weather_timezone is not None
        resolved = await geocoder.reverse_configured_coordinates(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            timezone=settings.weather_timezone,
        )
        return await select_weather_location(resolved, sessions=sessions)


async def weather_location_for_poll(settings: Settings) -> WeatherLocation | None:
    selected = await get_selected_weather_location()
    if selected is not None or not weather_configured(settings):
        return selected
    return await bootstrap_configured_location(settings)


def _to_location(row: WeatherLocationRow) -> WeatherLocation:
    return WeatherLocation(
        id=row.id,
        display_name=row.display_name,
        city=row.city,
        region=row.region,
        country=row.country,
        latitude=row.latitude,
        longitude=row.longitude,
        timezone=row.timezone,
        selected_at=row.selected_at,
        last_used_at=row.last_used_at,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("location timestamps must be timezone-aware")
    return value.astimezone(UTC)
