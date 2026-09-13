"""Provider-neutral football fixture discovery and health view."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.providers.football.models import FixtureSummary, FootballFixtureObservation


class FootballFixtureService:
    """Read-only fixture discovery contract backed by provider observations."""

    def __init__(self) -> None:
        self._fixtures: dict[int, FootballFixtureObservation] = {}
        self.last_observation_at: datetime | None = None
        self.quota: dict[str, Any] | None = None
        self.cadence: dict[str, Any] | None = None

    def replace(
        self,
        fixtures: list[FootballFixtureObservation],
        *,
        observed_at: datetime | None = None,
    ) -> None:
        self._fixtures = {fixture.fixture_id: fixture for fixture in fixtures}
        if observed_at:
            self.last_observation_at = observed_at.astimezone(UTC)

    def today(self, *, now: datetime | None = None) -> list[FixtureSummary]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return self._summaries(
            item for item in self._fixtures.values() if item.kickoff_at.date() == current.date()
        )

    def upcoming(
        self, *, now: datetime | None = None, within: timedelta = timedelta(days=7)
    ) -> list[FixtureSummary]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return self._summaries(
            item
            for item in self._fixtures.values()
            if current < item.kickoff_at <= current + within
            and item.status_code in {"NS", "TBD", "PST"}
        )

    def live(self) -> list[FixtureSummary]:
        return self._summaries(
            item
            for item in self._fixtures.values()
            if item.status_code in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}
        )

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        return {
            "last_observation_at": (
                self.last_observation_at.isoformat() if self.last_observation_at else None
            ),
            "cadence": self.cadence,
            "today": [item.model_dump(mode="json") for item in self.today(now=now)],
            "upcoming": [item.model_dump(mode="json") for item in self.upcoming(now=now)],
            "live": [item.model_dump(mode="json") for item in self.live()],
        }

    @staticmethod
    def _summaries(fixtures: Iterable[FootballFixtureObservation]) -> list[FixtureSummary]:
        return [
            FixtureSummary(
                fixture_id=item.fixture_id,
                subject_id=item.external_entity_id,
                competition=item.competition,
                home_team=item.home_team,
                away_team=item.away_team,
                kickoff_at=item.kickoff_at,
                status=item.status_label or item.status_code,
                minute=item.minute,
                home_score=item.home_score,
                away_score=item.away_score,
            )
            for item in sorted(fixtures, key=lambda row: (row.kickoff_at, row.fixture_id))
        ]


class FootballApiResponse(BaseModel):
    """Stable API shape for the today/upcoming/live football fixture lists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_status: str
    observed_at: datetime | None
    today: list[FixtureSummary]
    upcoming: list[FixtureSummary]
    live: list[FixtureSummary]


football_fixture_service = FootballFixtureService()
