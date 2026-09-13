"""Translate API-Football DTOs into provider-neutral fixture observations."""

import hashlib
import json
from datetime import UTC, datetime

from app.providers.football.models import (
    FixtureEvent,
    FixtureRecord,
    FootballFixtureObservation,
    NormalizedMatchEvent,
)


def normalize_fixture(
    fixture: FixtureRecord,
    *,
    canonical_competitions: dict[int, str],
    final_verification: bool = False,
) -> FootballFixtureObservation | None:
    competition = canonical_competitions.get(fixture.league.id)
    if competition is None:
        return None
    home, away = fixture.teams.home, fixture.teams.away
    status_code = fixture.fixture.status.short.upper()
    minute = fixture.fixture.status.elapsed
    if minute is None:
        if status_code == "HT":
            minute = 45
        elif status_code in {"AET", "PEN"}:
            minute = 120
        elif status_code == "FT":
            minute = 90
        else:
            minute = 0
    minute = min(130, max(0, minute + (fixture.fixture.status.extra or 0)))
    events = tuple(
        normalized
        for raw in fixture.events or ()
        if (normalized := _normalize_event(raw, fixture, minute)) is not None
    )
    return FootballFixtureObservation(
        fixture_id=fixture.fixture.id,
        league_id=fixture.league.id,
        competition=competition,
        home_team=home.name,
        away_team=away.name,
        home_team_id=home.id,
        away_team_id=away.id,
        kickoff_at=fixture.fixture.date,
        actual_kickoff_at=(
            datetime.fromtimestamp(fixture.fixture.periods.first, UTC)
            if fixture.fixture.periods.first is not None
            else None
        ),
        status_code=status_code,
        status_label=fixture.fixture.status.long,
        minute=minute,
        home_score=fixture.goals.home,
        away_score=fixture.goals.away,
        events=events,
        final_verification=final_verification,
    )


def _normalize_event(
    event: FixtureEvent, fixture: FixtureRecord, current_minute: int
) -> NormalizedMatchEvent | None:
    elapsed = event.time.elapsed if event.time.elapsed is not None else current_minute
    minute = min(130, max(0, elapsed + (event.time.extra or 0)))
    team_id = event.team.id if event.team else None
    team_name = event.team.name if event.team else None
    side = None
    if team_id is not None:
        if team_id == fixture.teams.home.id:
            side = "home"
        elif team_id == fixture.teams.away.id:
            side = "away"
    elif team_name:
        normalized = team_name.casefold()
        if normalized == fixture.teams.home.name.casefold():
            side = "home"
        elif normalized == fixture.teams.away.name.casefold():
            side = "away"

    kind = event.type.strip()
    if kind.casefold() not in {"goal", "card", "subst", "substitution"}:
        return None
    identity_fields: dict[str, object] = {
        "fixture": fixture.fixture.id,
        "type": kind.casefold(),
        "minute": elapsed,
        "extra": event.time.extra,
        "team": team_id if team_id is not None else team_name,
        "player": (
            event.player.id or event.player.name if event.player else None
        ),
    }
    if kind.casefold() != "goal":
        identity_fields["detail"] = (event.detail or "").casefold()
        identity_fields["assist"] = (
            event.assist.id or event.assist.name if event.assist else None
        )
    identity = hashlib.sha256(
        json.dumps(identity_fields, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return NormalizedMatchEvent(
        identity=identity,
        kind=kind,
        minute=minute,
        side=side,
        player=event.player.name if event.player else None,
        assist=event.assist.name if event.assist else None,
        detail=event.detail,
    )
