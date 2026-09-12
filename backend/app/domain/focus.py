from datetime import UTC, datetime, timedelta
from enum import IntEnum


class Attention(IntEnum):
    LOW = 20
    NORMAL = 40
    HIGH = 70
    CRITICAL = 95


EVENT_ATTENTION_TTL = timedelta(seconds=12)


def attention_for(
    status: str,
    latest_event_type: str | None,
    event_at: datetime | None = None,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(UTC)
    if (
        latest_event_type in {"football.match.goal", "football.match.red_card"}
        and event_at is not None
        and timedelta(0) <= current_time - event_at.astimezone(UTC) <= EVENT_ATTENTION_TTL
    ):
        return int(Attention.CRITICAL)
    if status in {"live", "halftime"}:
        return int(Attention.HIGH)
    if status == "scheduled":
        return int(Attention.NORMAL)
    return int(Attention.LOW)
