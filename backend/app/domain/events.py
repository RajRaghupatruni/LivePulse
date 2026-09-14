from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid6 import uuid7


class FootballEventType(StrEnum):
    SCHEDULED = "football.match.scheduled"
    KICKOFF = "football.match.kickoff"
    GOAL = "football.match.goal"
    SCORE_CORRECTED = "football.match.score_corrected"
    YELLOW_CARD = "football.match.yellow_card"
    RED_CARD = "football.match.red_card"
    SUBSTITUTION = "football.match.substitution"
    HALFTIME = "football.match.halftime"
    SECOND_HALF = "football.match.second_half"
    EXTRA_TIME = "football.match.extra_time"
    PENALTIES = "football.match.penalties"
    FULLTIME = "football.match.fulltime"


class FootballPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    home_team: str
    away_team: str
    competition: str = "Premier League"
    minute: int = Field(default=0, ge=0, le=130)
    current_minute: int | None = Field(default=None, ge=0, le=130)
    side: Literal["home", "away"] | None = None
    player: str | None = None
    substitute: str | None = None
    detail: str | None = None
    home_score: int = Field(default=0, ge=0)
    away_score: int = Field(default=0, ge=0)
    status: str | None = None
    phase: str | None = None


class FrozenDict(dict[str, Any]):
    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("canonical event payloads are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid7)
    source: str
    event_type: str
    subject_type: str = "match"
    subject_id: str
    occurred_at: datetime
    observed_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(ge=1)
    dedupe_key: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    correlation_id: UUID
    payload: dict[str, Any]

    @field_validator("occurred_at", "observed_at", "ingested_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("canonical timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("payload")
    @classmethod
    def freeze_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _deep_freeze(value)


def utc_now() -> datetime:
    return datetime.now(UTC)
