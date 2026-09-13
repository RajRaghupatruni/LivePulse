"""Weather current-state and freshness endpoints for final UI integration."""

from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings
from app.providers.weather.service import weather_state

router = APIRouter()


@router.get("/api/v1/providers/weather/current")
async def weather_current() -> dict[str, Any]:
    return weather_state.response(get_settings())


@router.get("/api/v1/providers/weather/health")
async def weather_health() -> dict[str, object]:
    return weather_state.health_snapshot(get_settings())
