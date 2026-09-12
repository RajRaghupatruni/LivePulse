"""Small capability protocols shared by the five locked provider streams."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from app.providers.commands import CommandRequest, CommandResult
from app.providers.observations import Observation


@dataclass(frozen=True, slots=True)
class PollSchedule:
    interval: timedelta
    timeout: timedelta = timedelta(seconds=15)
    max_backoff: timedelta = timedelta(minutes=5)
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.interval <= timedelta(0) or self.timeout <= timedelta(0):
            raise ValueError("poll interval and timeout must be positive")
        if self.max_backoff < self.interval:
            raise ValueError("max_backoff cannot be shorter than interval")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PollContext:
    correlation_id: UUID
    scheduled_at: datetime
    checkpoint: str | None = None

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        object.__setattr__(self, "scheduled_at", self.scheduled_at.astimezone(UTC))


class PollSource(Protocol):
    provider_id: str
    schedule: PollSchedule

    def cadence(self, *, context: PollContext) -> timedelta: ...

    async def observe(self, *, context: PollContext) -> Sequence[Observation[BaseModel]]: ...


class WebhookSource(Protocol):
    provider_id: str

    async def verify(self, *, headers: Mapping[str, str], body: bytes) -> bool: ...

    async def normalize(
        self, *, headers: Mapping[str, str], body: bytes, observed_at: datetime
    ) -> Sequence[Observation[BaseModel]]: ...


class CommandTarget(Protocol):
    provider_id: str

    @property
    def supported_commands(self) -> frozenset[str]: ...

    async def execute(self, request: CommandRequest) -> CommandResult: ...


class HealthReportingProvider(Protocol):
    provider_id: str

    def health_snapshot(self) -> BaseModel: ...
