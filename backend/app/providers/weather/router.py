"""Weather conditions and selectable normalized location endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.providers.status import provider_health
from app.providers.weather.client import WeatherConditions
from app.providers.weather.geocoding import GeocodingError, weather_geocoder
from app.providers.weather.location import WeatherLocation
from app.providers.weather.locations import (
    get_weather_location_state,
    select_weather_location,
)
from app.providers.weather.service import weather_configured, weather_state
from app.providers.weather.storage import weather_checkpoints

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/api/v1/providers/weather/current")
async def weather_current() -> dict[str, Any]:
    settings = get_settings()
    try:
        locations = await get_weather_location_state(settings)
    except SQLAlchemyError:
        log.warning(
            "weather snapshot unavailable because the location store could not be read",
            extra={"provider": "weather", "error_code": "location_store_unavailable"},
        )
        return {
            "location": None,
            "recent_locations": [],
            "current": None,
            "fetched_at": None,
            "health": weather_state.health_snapshot(settings),
        }
    selected = locations["selected"]
    current = None
    fetched_at = None
    if isinstance(selected, WeatherLocation):
        saved = await weather_checkpoints((f"current:{selected.id}",))
        if saved.get(f"current:{selected.id}"):
            try:
                current = WeatherConditions.model_validate_json(
                    saved[f"current:{selected.id}"]
                )
                fetched_at = current.observed_at.isoformat()
                weather_state.restore(
                    current, fetched_at=current.observed_at, location_id=selected.id
                )
            except ValidationError:
                current = None
        if current is None:
            current = weather_state.current(location_id=selected.id)
    return {
        "location": selected.model_dump(mode="json") if selected else None,
        "recent_locations": [
            location.model_dump(mode="json") for location in locations["recent"]
        ],
        "current": current.model_dump(mode="json") if current else None,
        "fetched_at": fetched_at or (current.observed_at.isoformat() if current else None),
        "health": weather_state.health_snapshot(
            settings,
            configured=bool(selected) or weather_configured(settings),
        ),
    }


@router.get("/api/v1/providers/weather/health")
async def weather_health() -> dict[str, object]:
    settings = get_settings()
    locations = await get_weather_location_state(settings)
    return weather_state.health_snapshot(
        settings, configured=bool(locations["selected"]) or weather_configured(settings)
    )


@router.get("/api/v1/providers/weather/location")
async def weather_location() -> dict[str, object]:
    settings = get_settings()
    try:
        state = await get_weather_location_state(settings)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "location_store_unavailable",
                "message": "Weather location storage is unavailable.",
            },
        ) from exc
    return {
        "selected": state["selected"].model_dump(mode="json")
        if state["selected"]
        else None,
        "recent": [location.model_dump(mode="json") for location in state["recent"]],
    }


@router.get("/api/v1/providers/weather/location/search")
async def search_weather_locations(
    q: str = Query(min_length=2, max_length=80),
) -> dict[str, object]:
    try:
        results = await weather_geocoder.search(q)
    except GeocodingError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.detail_code,
                "message": "Location search is temporarily unavailable.",
            },
        ) from exc
    return {"results": [location.model_dump(mode="json") for location in results]}


@router.post("/api/v1/providers/weather/location/select")
async def select_weather_location_route(
    location: WeatherLocation, request: Request
) -> dict[str, object]:
    settings = get_settings()
    selected = await select_weather_location(location)
    provider_health.report(
        "weather", "connecting", "location_changed", configured=True
    )
    scheduler = getattr(request.app.state, "poll_scheduler", None)
    if scheduler is not None:
        try:
            await scheduler.poll_now("weather")
        except Exception as exc:
            detail_code = getattr(exc, "detail_code", "weather_refresh_failed")
            log.warning(
                "weather refresh after location selection failed",
                extra={"provider": "weather", "error_code": detail_code},
            )
    state = await get_weather_location_state(settings)
    # A concurrent selection may have superseded this request while its forecast ran.
    current_selected = state["selected"]
    return {
        "selected": current_selected.model_dump(mode="json")
        if current_selected
        else selected.model_dump(mode="json"),
        "recent": [item.model_dump(mode="json") for item in state["recent"]],
    }
