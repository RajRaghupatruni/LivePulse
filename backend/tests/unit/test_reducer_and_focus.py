from datetime import UTC, datetime

from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.domain.focus import Attention, attention_for
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


def test_focus_engine_uses_deterministic_event_priority() -> None:
    assert attention_for("live", "football.match.goal") == int(Attention.CRITICAL)
    assert attention_for("live", "football.match.red_card") == int(Attention.CRITICAL)
    assert attention_for("live", "football.match.kickoff") == int(Attention.HIGH)
    assert attention_for("halftime", "football.match.halftime") == int(Attention.HIGH)
    assert attention_for("scheduled", None) == int(Attention.NORMAL)
    assert attention_for("idle", None) == int(Attention.LOW)
