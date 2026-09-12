from enum import IntEnum


class Attention(IntEnum):
    LOW = 20
    NORMAL = 40
    HIGH = 70
    CRITICAL = 95


def attention_for(status: str, latest_event_type: str | None) -> int:
    if latest_event_type in {"football.match.goal", "football.match.red_card"}:
        return int(Attention.CRITICAL)
    if status in {"live", "halftime"}:
        return int(Attention.HIGH)
    if status == "scheduled":
        return int(Attention.NORMAL)
    return int(Attention.LOW)
