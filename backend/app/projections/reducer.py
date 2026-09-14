from datetime import UTC, datetime
from typing import Any

from app.domain.events import CanonicalEvent


def reduce_match_state(current: dict[str, Any] | None, event: CanonicalEvent) -> dict[str, Any]:
    """Pure deterministic reducer. Older/equal event versions cannot regress state."""
    payload = event.payload
    if current and event.version <= current["version"]:
        return current
    # Keep delayed post-match facts in the timeline without allowing them to
    # rewrite the authoritative final score or phase. Explicit score corrections
    # remain valid because they represent a corrected final result.
    if (
        current
        and current["status"] == "fulltime"
        and not event.event_type.endswith(".score_corrected")
    ):
        return current
    state = {
        "match_id": event.subject_id,
        "home_team": str(payload["home_team"]),
        "away_team": str(payload["away_team"]),
        "competition": str(payload.get("competition", "Premier League")),
        "home_score": current["home_score"] if current else 0,
        "away_score": current["away_score"] if current else 0,
        "status": current["status"] if current else "scheduled",
        "minute": max(
            current["minute"] if current else 0,
            int(payload.get("current_minute", payload.get("minute", 0))),
        ),
        "phase": current["phase"] if current else "pre_match",
        "version": event.version,
        "last_event_id": event.event_id,
        "last_event_type": event.event_type,
        "updated_at": datetime.now(UTC),
    }
    if event.event_type.endswith(".scheduled"):
        state.update(status="scheduled", phase="pre_match")
    elif event.event_type.endswith(".kickoff"):
        state.update(status="live", phase="first_half")
    elif event.event_type.endswith(".goal"):
        if payload.get("side") == "home":
            state["home_score"] += 1
        elif payload.get("side") == "away":
            state["away_score"] += 1
        else:
            raise ValueError("goal event requires side=home or side=away")
        if state["status"] not in {"fulltime", "halftime"}:
            phase = state["phase"]
            if phase in {"pre_match", "scheduled", "unknown"}:
                phase = "second_half" if state["minute"] >= 45 else "first_half"
            elif phase == "first_half" and state["minute"] >= 45:
                phase = "second_half"
            state.update(status="live", phase=phase)
    elif event.event_type.endswith(".score_corrected"):
        state.update(home_score=int(payload["home_score"]), away_score=int(payload["away_score"]))
    elif event.event_type.endswith(".yellow_card") or event.event_type.endswith(".red_card"):
        if state["status"] not in {"fulltime", "halftime"}:
            state.update(
                status="live",
                phase=("second_half" if state["minute"] >= 45 else "first_half")
                if state["phase"] in {"pre_match", "scheduled", "unknown"}
                else state["phase"],
            )
    elif event.event_type.endswith(".substitution"):
        if state["status"] not in {"fulltime", "halftime"}:
            state.update(
                status="live",
                phase=("second_half" if state["minute"] >= 45 else "first_half")
                if state["phase"] in {"pre_match", "scheduled", "unknown"}
                else state["phase"],
            )
    elif event.event_type.endswith(".halftime"):
        if state["status"] != "fulltime":
            state.update(status="halftime", phase="halftime")
    elif event.event_type.endswith(".second_half"):
        if state["status"] != "fulltime":
            state.update(status="live", phase="second_half")
    elif event.event_type.endswith(".extra_time"):
        if state["status"] != "fulltime":
            state.update(status="live", phase="extra_time", minute=max(90, state["minute"]))
    elif event.event_type.endswith(".penalties"):
        if state["status"] != "fulltime":
            state.update(status="live", phase="penalties", minute=max(120, state["minute"]))
    elif event.event_type.endswith(".fulltime"):
        state.update(status="fulltime", phase="fulltime")
    return state
