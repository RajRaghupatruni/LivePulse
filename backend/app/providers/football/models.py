"""Typed API-Football DTOs and vendor-neutral football observations."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderDto(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class LeagueInfo(ProviderDto):
    id: int
    name: str
    type: str | None = None


class LeagueSeason(ProviderDto):
    year: int
    current: bool = False


class LeagueCountry(ProviderDto):
    name: str


class LeagueRecord(ProviderDto):
    league: LeagueInfo
    country: LeagueCountry | str | None = None
    seasons: list[LeagueSeason] = Field(default_factory=list)


class FixtureStatus(ProviderDto):
    long: str | None = None
    short: str = "TBD"
    elapsed: int | None = None
    extra: int | None = None


class FixturePeriods(ProviderDto):
    first: int | None = None
    second: int | None = None


class FixtureInfo(ProviderDto):
    id: int
    date: datetime
    timestamp: int | None = None
    timezone: str | None = None
    periods: FixturePeriods = Field(default_factory=FixturePeriods)
    status: FixtureStatus

    @field_validator("date")
    @classmethod
    def require_aware_date(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fixture date must include a timezone")
        return value.astimezone(UTC)


class TeamInfo(ProviderDto):
    id: int | None = None
    name: str


class FixtureTeams(ProviderDto):
    home: TeamInfo
    away: TeamInfo


class FixtureLeague(ProviderDto):
    id: int
    name: str
    country: str | None = None
    season: int | None = None


class FixtureScore(ProviderDto):
    home: int | None = None
    away: int | None = None


class FixtureScores(ProviderDto):
    halftime: FixtureScore | None = None
    fulltime: FixtureScore | None = None
    extratime: FixtureScore | None = None
    penalty: FixtureScore | None = None


class EventTime(ProviderDto):
    elapsed: int | None = None
    extra: int | None = None


class EventParty(ProviderDto):
    id: int | None = None
    name: str | None = None


class FixtureEvent(ProviderDto):
    time: EventTime = Field(default_factory=EventTime)
    team: EventParty | None = None
    player: EventParty | None = None
    assist: EventParty | None = None
    type: str
    detail: str | None = None
    comments: str | None = None


class FixtureRecord(ProviderDto):
    fixture: FixtureInfo
    league: FixtureLeague
    teams: FixtureTeams
    goals: FixtureScore = Field(default_factory=FixtureScore)
    score: FixtureScores = Field(default_factory=FixtureScores)
    events: list[FixtureEvent] | None = None


class PagingInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    current: int = 1
    total: int = 1


class ApiEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    errors: dict[str, Any] | list[Any] = Field(default_factory=list)
    results: int = 0
    paging: PagingInfo = Field(default_factory=PagingInfo)
    response: list[Any] = Field(default_factory=list)


class LeagueEnvelope(ApiEnvelope):
    response: list[LeagueRecord] = Field(default_factory=list)


class FixtureEnvelope(ApiEnvelope):
    response: list[FixtureRecord] = Field(default_factory=list)


class NormalizedMatchEvent(BaseModel):
    """Small provider-neutral event representation used inside football ingestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: str = Field(min_length=1, max_length=255)
    kind: str
    minute: int = Field(default=0, ge=0, le=130)
    side: str | None = None
    player: str | None = None
    assist: str | None = None
    detail: str | None = None


class FootballFixtureObservation(BaseModel):
    """Normalized fixture snapshot. It intentionally contains no API vendor DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: int = Field(gt=0)
    league_id: int = Field(gt=0)
    competition: str
    home_team: str
    away_team: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    kickoff_at: datetime
    actual_kickoff_at: datetime | None = None
    status_code: str
    status_label: str | None = None
    minute: int = Field(default=0, ge=0, le=130)
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    events: tuple[NormalizedMatchEvent, ...] = ()
    final_verification: bool = False

    @field_validator("kickoff_at")
    @classmethod
    def require_utc_kickoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kickoff_at must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def external_entity_id(self) -> str:
        return f"api-football:fixture:{self.fixture_id}"

    @property
    def event_time(self) -> datetime:
        """Approximate occurrence time from elapsed minute when the API has no timestamp."""

        return (self.actual_kickoff_at or self.kickoff_at) + timedelta(
            minutes=max(0, self.minute)
        )


class FixtureSummary(BaseModel):
    """App-facing, provider-neutral contract for football fixture discovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: int
    subject_id: str
    competition: str
    home_team: str
    away_team: str
    kickoff_at: datetime
    status: str
    minute: int
    home_score: int | None
    away_score: int | None
