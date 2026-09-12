"""Provider-neutral observations that stop before canonical event normalization."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Observation[ContentT: BaseModel](BaseModel):
    """A normalized provider observation, not an event or authoritative projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,49}$")
    external_entity_id: str = Field(min_length=1, max_length=300)
    observed_at: datetime
    content: ContentT
    provider_version: str | None = Field(default=None, max_length=255)
    checkpoint: str | None = Field(default=None, max_length=4096)
    correlation_id: UUID | None = None

    @field_validator("observed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(UTC)
