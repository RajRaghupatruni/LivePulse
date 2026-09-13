"""Quota-aware cadence policy for football fixture polling."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.providers.football.models import FootballFixtureObservation


@dataclass(frozen=True, slots=True)
class CadenceDecision:
    interval: timedelta
    reason: str


def adaptive_cadence_decision(
    fixtures: Iterable[FootballFixtureObservation],
    *,
    now: datetime,
    quota_remaining: int,
    minute_remaining: int | None = None,
    request_cost: int = 1,
) -> CadenceDecision:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if request_cost < 1:
        raise ValueError("request_cost must be positive")
    current = now.astimezone(UTC)
    items = tuple(fixtures)
    if quota_remaining <= 5:
        return CadenceDecision(timedelta(hours=12), "daily_budget_exhausted")

    pending_final = any(item.final_verification for item in items)
    live = [item for item in items if item.status_code in {"1H", "2H", "ET", "BT", "P", "LIVE"}]
    halftime = any(item.status_code == "HT" for item in items)
    is_live_window = bool(live or halftime)

    if pending_final:
        cadence, reason = timedelta(minutes=2), "final_verification_pending"
    elif live:
        cadence, reason = timedelta(seconds=150 * request_cost), "active_live_match"
    elif halftime:
        cadence, reason = timedelta(minutes=5 * request_cost), "halftime_match"
    else:
        upcoming = [
            item.kickoff_at
            for item in items
            if item.status_code in {"NS", "TBD", "PST"} and item.kickoff_at > current
        ]
        if not upcoming:
            cadence, reason = timedelta(hours=12), "no_live_or_upcoming_match"
        else:
            until_kickoff = min(upcoming) - current
            if until_kickoff <= timedelta(minutes=5):
                cadence, reason = timedelta(seconds=150), "upcoming_match_within_5m"
            elif until_kickoff <= timedelta(minutes=30):
                cadence, reason = timedelta(minutes=5), "upcoming_match_within_30m"
            elif until_kickoff <= timedelta(hours=3):
                cadence, reason = timedelta(minutes=30), "upcoming_match_within_3h"
            elif until_kickoff <= timedelta(hours=6):
                cadence, reason = timedelta(hours=1), "upcoming_match_within_6h"
            else:
                cadence = min(
                    timedelta(hours=12),
                    max(timedelta(hours=3), until_kickoff - timedelta(hours=6)),
                )
                reason = "upcoming_match_discovery"

    if minute_remaining is not None and minute_remaining <= 1 and is_live_window:
        cadence = max(cadence, timedelta(minutes=1))
        reason = "minute_quota_tight"

    # The live query batches all locked competitions into one request. When the
    # API omits event details, the extra IDs request is included in request_cost.
    # Reserve five of the 100 daily calls for recovery and avoid spending the
    # remaining quota as if every active day had the same amount of play.
    if is_live_window:
        if quota_remaining <= 15:
            floor, quota_reason = timedelta(minutes=10), "daily_quota_degraded_10m"
        elif quota_remaining <= 30:
            floor, quota_reason = timedelta(minutes=5), "daily_quota_degraded_5m"
        elif quota_remaining <= 50:
            floor, quota_reason = timedelta(minutes=3), "daily_quota_degraded_3m"
        else:
            floor, quota_reason = timedelta(0), reason
        if floor:
            cadence = max(cadence, floor * request_cost)
            reason = quota_reason
    elif quota_remaining <= 15:
        cadence = max(cadence, timedelta(minutes=10))
        reason = "daily_quota_tight_no_live_match"
    elif quota_remaining <= 30:
        cadence = max(cadence, timedelta(minutes=5))
        reason = "daily_quota_low_no_live_match"

    return CadenceDecision(cadence, reason)


def adaptive_cadence(
    fixtures: Iterable[FootballFixtureObservation],
    *,
    now: datetime,
    quota_remaining: int,
    minute_remaining: int | None = None,
    request_cost: int = 1,
) -> timedelta:
    """Compatibility convenience returning the interval from the policy decision."""

    return adaptive_cadence_decision(
        fixtures,
        now=now,
        quota_remaining=quota_remaining,
        minute_remaining=minute_remaining,
        request_cost=request_cost,
    ).interval
