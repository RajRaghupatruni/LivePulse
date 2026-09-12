from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Attention(IntEnum):
    LOW = 10
    NORMAL = 40
    HIGH = 70
    CRITICAL = 95


EVENT_ATTENTION_TTL = timedelta(seconds=12)


class FocusState(BaseModel):
    """Normalized, deterministic focus decision for a current subject."""

    model_config = ConfigDict(frozen=True)

    score: int
    severity: Literal["low", "normal", "high", "critical"]
    reason: str
    transient: bool
    expires_at: datetime | None
    source: str
    subject_id: str | None
    match_mode: Literal["idle", "scheduled", "live", "halftime", "highlight", "fulltime"]


def focus_for_match(
    status: str,
    latest_event_type: str | None,
    event_at: datetime | None = None,
    now: datetime | None = None,
    *,
    subject_id: str | None = None,
    source: str = "football",
) -> FocusState:
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    event_time = event_at.astimezone(UTC) if event_at is not None else None
    age = current_time - event_time if event_time is not None else None

    if (
        latest_event_type in {"football.match.goal", "football.match.red_card"}
        and age is not None
        and timedelta(0) <= age <= EVENT_ATTENTION_TTL
    ):
        is_goal = latest_event_type == "football.match.goal"
        return FocusState(
            score=100 if is_goal else 95,
            severity="critical",
            reason="goal" if is_goal else "red_card",
            transient=True,
            expires_at=event_time + EVENT_ATTENTION_TTL,
            source=source,
            subject_id=subject_id,
            match_mode="highlight",
        )

    if status == "live":
        score, severity, reason, mode = 70, "high", "live_match", "live"
    elif status == "halftime":
        score, severity, reason, mode = 52, "normal", "halftime_break", "halftime"
    elif status == "scheduled":
        score, severity, reason, mode = 40, "normal", "scheduled_match", "scheduled"
    elif status == "fulltime":
        score, severity, reason, mode = 30, "low", "fulltime", "fulltime"
    else:
        score, severity, reason, mode = 10, "low", "no_active_match", "idle"

    if latest_event_type == "football.match.yellow_card" and status == "live":
        reason = "yellow_card"
    return FocusState(
        score=score,
        severity=severity,  # type: ignore[arg-type]
        reason=reason,
        transient=False,
        expires_at=None,
        source=source,
        subject_id=subject_id,
        match_mode=mode,  # type: ignore[arg-type]
    )


def attention_for(
    status: str,
    latest_event_type: str | None,
    event_at: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """Compatibility helper for callers that only need a score."""
    return focus_for_match(status, latest_event_type, event_at, now).score
