"""Read-only HTTP contract for relevant football fixtures."""

from fastapi import APIRouter

from app.providers.football.service import (
    FootballApiResponse,
    football_fixture_service,
)
from app.providers.status import provider_health

router = APIRouter(prefix="/api/v1/football", tags=["football"])


@router.get("/fixtures", response_model=FootballApiResponse)
async def football_fixtures() -> FootballApiResponse:
    health = provider_health.snapshot().get("football", {})
    return FootballApiResponse(
        provider_status=str(health.get("status", "unknown")),
        observed_at=football_fixture_service.last_observation_at,
        today=football_fixture_service.today(),
        upcoming=football_fixture_service.upcoming(),
        live=football_fixture_service.live(),
    )
