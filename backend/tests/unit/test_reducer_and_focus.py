from datetime import UTC, datetime, timedelta

from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.domain.focus import Attention, attention_for, focus_for_match
from app.projections.reducer import reduce_match_state


def event(event_type: str, version: int, **payload: object) -> CanonicalEvent:
    return CanonicalEvent(
        source="test",
        event_type=event_type,
        subject_id="match-1",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=version,
        dedupe_key=f"test:{version}",
        correlation_id=uuid7(),
        payload={"home_team": "Northstar", "away_team": "Harbor", "minute": 30, **payload},
    )


def test_projection_transitions_and_ignores_stale_versions() -> None:
    state = reduce_match_state(None, event("football.match.scheduled", 1))
    state = reduce_match_state(state, event("football.match.kickoff", 2))
    state = reduce_match_state(state, event("football.match.goal", 3, side="home"))
    assert state["status"] == "live"
    assert (state["home_score"], state["away_score"]) == (1, 0)
    stale = reduce_match_state(state, event("football.match.goal", 2, side="away"))
    assert stale == state
    state = reduce_match_state(state, event("football.match.goal", 4, side="away"))
    state = reduce_match_state(state, event("football.match.fulltime", 5, minute=90))
    assert (state["home_score"], state["away_score"], state["status"]) == (1, 1, "fulltime")


def test_late_goal_does_not_change_final_match_state() -> None:
    state = reduce_match_state(None, event("football.match.scheduled", 1))
    state = reduce_match_state(state, event("football.match.kickoff", 2))
    state = reduce_match_state(state, event("football.match.goal", 3, side="home"))
    state = reduce_match_state(state, event("football.match.fulltime", 4, minute=90))

    late_goal = reduce_match_state(
        state,
        event("football.match.goal", 5, side="away", minute=35),
    )

    assert late_goal == state


def test_live_card_fact_resolves_phase_instead_of_leaving_a_prematch_projection() -> None:
    scheduled = reduce_match_state(None, event("football.match.scheduled", 1))
    card = reduce_match_state(
        scheduled,
        event("football.match.yellow_card", 2, minute=42, side="away"),
    )

    assert (card["status"], card["phase"], card["minute"]) == ("live", "first_half", 42)


def test_focus_engine_uses_deterministic_event_priority() -> None:
    now = datetime.now(UTC)
    goal = focus_for_match("live", "football.match.goal", now, now, subject_id="match-1")
    red_card = focus_for_match("live", "football.match.red_card", now, now)
    assert (goal.score, goal.severity, goal.reason, goal.transient) == (
        100,
        "critical",
        "goal",
        True,
    )
    assert goal.expires_at == now + timedelta(seconds=12)
    assert (red_card.score, red_card.reason, red_card.match_mode) == (95, "red_card", "highlight")
    assert attention_for("live", "football.match.goal", now, now + timedelta(seconds=13)) == int(
        Attention.HIGH
    )
    settled = focus_for_match("live", "football.match.goal", now, now + timedelta(seconds=13))
    assert (settled.score, settled.reason, settled.transient, settled.match_mode) == (
        70,
        "live_match",
        False,
        "live",
    )
    assert attention_for("live", "football.match.yellow_card", now, now) == int(Attention.HIGH)
    assert focus_for_match("live", "football.match.kickoff").match_mode == "live"
    assert focus_for_match("halftime", "football.match.halftime").score == 52
    assert focus_for_match("scheduled", None).score == int(Attention.NORMAL)
    assert focus_for_match("fulltime", "football.match.fulltime").match_mode == "fulltime"
    assert focus_for_match("idle", None).score == int(Attention.LOW)
