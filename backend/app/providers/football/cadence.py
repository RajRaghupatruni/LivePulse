"""Quota-aware cadence policy for football fixture polling."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app.providers.football.models import FootballFixtureObservation


def adaptive_cadence(
    fixtures: Iterable[FootballFixtureObservation],
    *,
    now: datetime,
    quota_remaining: int,
    minute_remaining: int | None = None,
) -> timedelta:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(UTC)
    items = tuple(fixtures)
    if quota_remaining <= 5:
        return timedelta(hours=1)
    if minute_remaining is not None and minute_remaining <= 1:
        return timedelta(minutes=1)

    pending_final = any(item.final_verification for item in items)
    live = [item for item in items if item.status_code in {"1H", "2H", "ET", "BT", "P"}]
    halftime = any(item.status_code == "HT" for item in items)
    if pending_final:
        cadence = timedelta(minutes=2)
    elif live:
        cadence = timedelta(minutes=10)
    elif halftime:
        cadence = timedelta(minutes=18)
    else:
        upcoming = [
            item.kickoff_at
            for item in items
            if item.status_code in {"NS", "TBD", "PST"} and item.kickoff_at > current
        ]
        if not upcoming:
            cadence = timedelta(hours=12)
        else:
            until_kickoff = min(upcoming) - current
            if until_kickoff <= timedelta(minutes=30):
                cadence = timedelta(minutes=12)
            elif until_kickoff <= timedelta(hours=3):
                cadence = timedelta(minutes=30)
            elif until_kickoff <= timedelta(hours=6):
                cadence = timedelta(hours=1)
            else:
                cadence = min(
                    timedelta(hours=12),
                    max(timedelta(hours=3), until_kickoff - timedelta(hours=6)),
                )

    if quota_remaining <= 15:
        cadence = max(cadence, timedelta(minutes=60))
    elif quota_remaining <= 30:
        cadence = max(cadence, timedelta(minutes=30))
    elif quota_remaining <= 50:
        cadence = max(cadence, timedelta(minutes=15))
    return cadence
