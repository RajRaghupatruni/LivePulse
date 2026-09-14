"""Deterministic fixture-state comparison and canonical event creation."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.domain.events import CanonicalEvent, FootballEventType, FootballPayload
from app.providers.football.models import FootballFixtureObservation, NormalizedMatchEvent
from app.providers.observations import Observation

LIVE_CODES = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE"})
FULLTIME_CODES = frozenset({"FT", "AET", "PEN"})
CANCELLED_CODES = frozenset({"CANC", "ABD", "AWD", "WO"})
STATUS_RANK = {
    "TBD": 0,
    "NS": 0,
    "PST": 0,
    "SUSP": 1,
    "INT": 1,
    "1H": 1,
    "HT": 2,
    "2H": 3,
    "ET": 4,
    "BT": 4,
    "P": 4,
    "FT": 5,
    "AET": 5,
    "PEN": 5,
    "CANC": 5,
    "ABD": 5,
    "AWD": 5,
    "WO": 5,
}


def diff_fixture(
    previous: dict[str, Any] | None,
    observation: Observation[FootballFixtureObservation],
    *,
    correlation_id: UUID,
    emit_scheduled: bool = True,
) -> tuple[list[CanonicalEvent], dict[str, Any]]:
    """Create newly observed facts, then return a candidate checkpoint.

    ``emit_scheduled`` is false only while a provider's first successful
    synchronization establishes its existing-fixture baseline. Other facts
    (including live match events) retain their normal semantics.
    """

    fixture = observation.content
    prior = previous or {}
    event_ids = set(str(item) for item in prior.get("event_ids", []))
    emitted: list[CanonicalEvent] = []
    prior_version = int(prior.get("version", 0))
    version = prior_version
    previous_status = str(prior.get("status_code", "TBD")).upper()
    received_status = fixture.status_code.upper()
    stale = bool(prior) and (
        fixture.minute < int(prior.get("minute", 0))
        or STATUS_RANK.get(received_status, 0) < STATUS_RANK.get(previous_status, 0)
    )
    status_code = (
        previous_status
        if STATUS_RANK.get(received_status, 0) < STATUS_RANK.get(previous_status, 0)
        else received_status
    )
    minute = max(int(prior.get("minute", 0)), fixture.minute)
    old_home = int(prior.get("home_score", 0))
    old_away = int(prior.get("away_score", 0))
    current_home, current_away = old_home, old_away

    def emit(
        event_type: FootballEventType,
        *,
        identity: str,
        event_minute: int,
        occurred_at: datetime,
        side: str | None = None,
        player: str | None = None,
        substitute: str | None = None,
        detail: str | None = None,
        home_score: int | None = None,
        away_score: int | None = None,
        phase: str | None = None,
    ) -> None:
        nonlocal version, current_home, current_away
        version += 1
        resolved_home = current_home if home_score is None else home_score
        resolved_away = current_away if away_score is None else away_score
        if event_type == FootballEventType.GOAL:
            if side == "home" and home_score is None:
                resolved_home += 1
            elif side == "away" and away_score is None:
                resolved_away += 1
        payload = FootballPayload(
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            competition=fixture.competition,
            minute=min(130, max(0, event_minute)),
            current_minute=min(130, max(0, fixture.minute)),
            side=side,
            player=player,
            substitute=substitute,
            detail=detail,
            phase=phase,
            home_score=max(0, resolved_home),
            away_score=max(0, resolved_away),
            status=fixture.status_label or status_code,
        ).model_dump(mode="json", exclude_none=True)
        emitted.append(
            CanonicalEvent(
                source="api-football",
                event_type=event_type.value,
                subject_type="match",
                subject_id=fixture.external_entity_id,
                occurred_at=occurred_at,
                observed_at=observation.observed_at,
                version=version,
                dedupe_key=f"api-football:{fixture.fixture_id}:{identity}",
                correlation_id=correlation_id,
                payload=payload,
            )
        )
        current_home, current_away = resolved_home, resolved_away

    halftime_emitted = bool(prior.get("halftime_emitted"))
    second_half_emitted = bool(prior.get("second_half_emitted"))
    extra_time_emitted = bool(prior.get("extra_time_emitted"))
    penalties_emitted = bool(prior.get("penalties_emitted"))

    def ensure_halftime() -> None:
        nonlocal halftime_emitted
        if status_code in {"HT", "2H", "ET", "BT", "P", *FULLTIME_CODES} and not halftime_emitted:
            emit(
                FootballEventType.HALFTIME,
                identity="halftime",
                event_minute=45,
                occurred_at=actual_kickoff_at + timedelta(minutes=45),
            )
            halftime_emitted = True

    def ensure_second_half() -> None:
        nonlocal second_half_emitted
        if status_code in {"2H", "ET", "BT", "P", *FULLTIME_CODES} and not second_half_emitted:
            ensure_halftime()
            emit(
                FootballEventType.SECOND_HALF,
                identity="second-half",
                event_minute=45,
                occurred_at=actual_kickoff_at + timedelta(minutes=60),
            )
            second_half_emitted = True

    def ensure_extra_time() -> None:
        nonlocal extra_time_emitted
        if status_code in {"ET", "BT", "P", "AET", "PEN"} and not extra_time_emitted:
            ensure_second_half()
            emit(
                FootballEventType.EXTRA_TIME,
                identity="extra-time",
                event_minute=90,
                occurred_at=actual_kickoff_at + timedelta(minutes=90),
                phase="extra_time",
            )
            extra_time_emitted = True

    def ensure_penalties() -> None:
        nonlocal penalties_emitted
        if status_code in {"P", "PEN"} and not penalties_emitted:
            ensure_extra_time()
            emit(
                FootballEventType.PENALTIES,
                identity="penalties",
                event_minute=120,
                occurred_at=actual_kickoff_at + timedelta(minutes=120),
                phase="penalties",
            )
            penalties_emitted = True

    kickoff_at = fixture.kickoff_at
    actual_kickoff_at = fixture.actual_kickoff_at or kickoff_at
    kickoff_key = kickoff_at.isoformat()
    scheduled_changed = prior.get("scheduled_kickoff") != kickoff_key
    if emit_scheduled and scheduled_changed:
        emit(
            FootballEventType.SCHEDULED,
            identity=f"scheduled:{prior_version}:{kickoff_key}",
            event_minute=0,
            occurred_at=kickoff_at,
        )

    is_live_or_later = status_code in LIVE_CODES | FULLTIME_CODES
    if is_live_or_later and not prior.get("kickoff_emitted"):
        emit(
            FootballEventType.KICKOFF,
            identity="kickoff",
            event_minute=0,
            occurred_at=actual_kickoff_at,
        )

    known_goal_counts = {"home": 0, "away": 0}
    for event in sorted(fixture.events, key=lambda item: (item.minute, item.identity)):
        if event.minute >= 45:
            ensure_halftime()
        if event.minute > 45:
            ensure_second_half()
        if event.minute >= 90:
            ensure_extra_time()
        if event.minute >= 120:
            ensure_penalties()
        classified = _classify_event(event)
        if classified is None or event.identity in event_ids:
            continue
        event_type, side = classified
        if (
            event_type
            in {
                FootballEventType.GOAL,
                FootballEventType.YELLOW_CARD,
                FootballEventType.RED_CARD,
            }
            and not side
        ):
            continue
        emit(
            event_type,
            identity=f"event:{event.identity}",
            event_minute=event.minute,
            occurred_at=actual_kickoff_at + timedelta(minutes=event.minute),
            side=side,
            player=event.player,
            substitute=event.assist if event_type == FootballEventType.SUBSTITUTION else None,
            detail=event.detail,
        )
        event_ids.add(event.identity)
        if event_type == FootballEventType.GOAL and side:
            known_goal_counts[side] += 1

    ensure_halftime()
    ensure_second_half()
    ensure_extra_time()
    ensure_penalties()

    reported_home = fixture.home_score if fixture.home_score is not None else old_home
    reported_away = fixture.away_score if fixture.away_score is not None else old_away
    if stale:
        reported_home, reported_away = old_home, old_away

    expected_home = old_home + known_goal_counts["home"]
    expected_away = old_away + known_goal_counts["away"]
    aligned_score = {"home": expected_home, "away": expected_away}
    # If the score advanced but the event array omitted a goal, record a deterministic
    # generic goal. A repeated unchanged score never creates one.
    for side, reported in (("home", reported_home), ("away", reported_away)):
        for score_number in range(aligned_score[side] + 1, reported + 1):
            generic_identity = f"score-goal:{prior_version}:{side}:{score_number}:{minute}"
            emit(
                FootballEventType.GOAL,
                identity=generic_identity,
                event_minute=minute,
                occurred_at=fixture.event_time,
                side=side,
                detail="Goal detected from score change",
            )
            aligned_score[side] += 1

    if (reported_home, reported_away) != (aligned_score["home"], aligned_score["away"]):
        emit(
            FootballEventType.SCORE_CORRECTED,
            identity=(
                f"score-corrected:{prior_version}:"
                f"{aligned_score['home']}-{aligned_score['away']}:"
                f"{reported_home}-{reported_away}"
            ),
            event_minute=minute,
            occurred_at=fixture.event_time,
            home_score=reported_home,
            away_score=reported_away,
            detail=(
                f"Provider score corrected from {aligned_score['home']}-{aligned_score['away']}"
            ),
        )

    if status_code in FULLTIME_CODES and not prior.get("fulltime_emitted"):
        emit(
            FootballEventType.FULLTIME,
            identity="fulltime",
            event_minute=max(90, minute),
            occurred_at=fixture.event_time,
            home_score=reported_home,
            away_score=reported_away,
        )

    final_verification_pending = bool(prior.get("final_verification_pending"))
    if status_code in FULLTIME_CODES and not prior.get("fulltime_emitted"):
        final_verification_pending = True
    if fixture.final_verification:
        final_verification_pending = False

    state = {
        "fixture_id": fixture.fixture_id,
        "competition": fixture.competition,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "scheduled_kickoff": kickoff_key,
        "status_code": status_code,
        "minute": minute,
        "home_score": reported_home,
        "away_score": reported_away,
        "event_ids": sorted(event_ids),
        "scheduled_emitted": bool(
            prior.get("scheduled_emitted") or (emit_scheduled and scheduled_changed)
        ),
        "kickoff_emitted": bool(prior.get("kickoff_emitted") or is_live_or_later),
        "halftime_emitted": halftime_emitted,
        "second_half_emitted": second_half_emitted,
        "extra_time_emitted": extra_time_emitted,
        "penalties_emitted": penalties_emitted,
        "fulltime_emitted": bool(prior.get("fulltime_emitted") or status_code in FULLTIME_CODES),
        "final_verification_pending": final_verification_pending,
        "terminal": status_code in FULLTIME_CODES | CANCELLED_CODES,
        "version": version,
        "last_observed_at": observation.observed_at.isoformat(),
    }
    return emitted, state


def _classify_event(
    event: NormalizedMatchEvent,
) -> tuple[FootballEventType, str | None] | None:
    kind = event.kind.casefold()
    detail = (event.detail or "").casefold()
    if kind == "goal":
        if any(token in detail for token in ("disallowed", "missed penalty", "goal cancelled")):
            return None
        return FootballEventType.GOAL, event.side
    if kind == "card":
        if "second yellow" in detail or "red card" in detail or "straight red" in detail:
            return FootballEventType.RED_CARD, event.side
        if "yellow" in detail:
            return FootballEventType.YELLOW_CARD, event.side
        return None
    if kind in {"subst", "substitution"}:
        return FootballEventType.SUBSTITUTION, event.side
    return None
