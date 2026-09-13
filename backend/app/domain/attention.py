"""Normalized, server-owned cross-domain attention for the local browser UI."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DominantFocus(BaseModel):
    """One evidence-backed attention signal; it never replaces football FocusState."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    priority: int = Field(ge=0, le=100)
    domain: Literal["football", "gmail", "github", "system"]
    reason: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    subject_id: str | None = None
    event_id: str | None = None
    transient: bool
    created_at: datetime
    observed_at: datetime
    expires_at: datetime | None = None

    @field_validator("created_at", "observed_at", "expires_at")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attention timestamps must be timezone-aware")
        return value.astimezone(UTC)


def select_dominant_focus(candidates: list[DominantFocus]) -> DominantFocus | None:
    """Pick by priority, then newest observed evidence, then stable domain/id ties."""

    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (
            -candidate.priority,
            -candidate.observed_at.timestamp(),
            candidate.domain,
            candidate.subject_id or "",
            candidate.event_id or "",
        ),
    )
