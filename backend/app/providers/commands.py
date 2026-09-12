"""Typed, bounded command requests for future provider-backed actions."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid6 import uuid7

SpotifyCommand = Literal[
    "spotify.play",
    "spotify.pause",
    "spotify.next",
    "spotify.previous",
    "spotify.seek",
    "spotify.volume",
    "spotify.transfer_device",
]
CommandErrorCode = Literal[
    "provider_unavailable",
    "not_authenticated",
    "unsupported_command",
    "invalid_state",
    "rate_limited",
    "provider_error",
]


class CommandArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_seconds: int | None = Field(default=None, ge=0, le=86_400)
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    device_id: str | None = Field(default=None, min_length=1, max_length=200)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: SpotifyCommand
    arguments: CommandArguments = Field(default_factory=CommandArguments)
    correlation_id: UUID = Field(default_factory=uuid7)

    @model_validator(mode="after")
    def validate_arguments_for_command(self) -> "CommandRequest":
        required = {
            "spotify.seek": "position_seconds",
            "spotify.volume": "volume_percent",
            "spotify.transfer_device": "device_id",
        }.get(self.command)
        present = {
            "position_seconds": self.arguments.position_seconds is not None,
            "volume_percent": self.arguments.volume_percent is not None,
            "device_id": self.arguments.device_id is not None,
        }
        if required is None and any(present.values()):
            raise ValueError("this command does not accept arguments")
        if required is not None and not present[required]:
            raise ValueError(f"{self.command} requires {required}")
        if required is not None and sum(present.values()) != 1:
            raise ValueError(f"{self.command} accepts only {required}")
        return self


class CommandStateHint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str | None = Field(default=None, max_length=200)
    state: str | None = Field(default=None, max_length=64)
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_timestamp(self) -> "CommandStateHint":
        if self.observed_at is not None:
            if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
                raise ValueError("observed_at must be timezone-aware")
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        return self


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,49}$")
    error_code: CommandErrorCode | None = None
    message: str = Field(max_length=240)
    resulting_state_hint: CommandStateHint | None = None

    @model_validator(mode="after")
    def keep_error_state_consistent(self) -> "CommandResult":
        if self.success and self.error_code is not None:
            raise ValueError("successful command results cannot include an error code")
        if not self.success and self.error_code is None:
            raise ValueError("failed command results require a stable error code")
        return self
