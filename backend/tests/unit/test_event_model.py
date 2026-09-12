from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from app.domain.events import CanonicalEvent, FootballEventType
from app.ingestion.normalize import ProviderObservation, normalize_football_observation


def test_normalization_is_provider_independent_and_dedupe_key_is_stable() -> None:
    run_id = uuid7()
    now = datetime.now(UTC)
    observation = ProviderObservation(
        FootballEventType.GOAL,
        "demo-one",
        run_id,
        3,
        now,
        now,
        {"home_team": "Northstar", "away_team": "Harbor", "minute": 22, "side": "home"},
    )
    first = normalize_football_observation(observation)
    second = normalize_football_observation(observation)
    assert first.dedupe_key == second.dedupe_key == f"demo-football:{run_id}:3"
    assert first.subject_id == "demo-one"
    assert first.event_type == "football.match.goal"
    assert first.event_id != second.event_id


def test_canonical_events_are_immutable_and_validate_version() -> None:
    event = CanonicalEvent(
        source="demo",
        event_type=FootballEventType.KICKOFF.value,
        subject_id="match-1",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key="key-1",
        correlation_id=uuid7(),
        payload={"home_team": "A", "away_team": "B", "details": {"scorer": "A"}, "history": [1, 2]},
    )
    with pytest.raises(ValidationError):
        event.version = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        event.payload["home_team"] = "Changed"
    with pytest.raises(TypeError):
        event.payload["details"]["scorer"] = "Changed"
    assert event.model_dump(mode="json")["payload"]["history"] == [1, 2]
    with pytest.raises(ValidationError):
        CanonicalEvent(
            source="demo",
            event_type="unknown",
            subject_id="m",
            occurred_at=datetime.now(UTC),
            observed_at=datetime.now(UTC),
            version=0,
            dedupe_key="k",
            correlation_id=uuid7(),
            payload={},
        )


def test_canonical_timestamps_are_timezone_aware_and_stored_as_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    event = CanonicalEvent(
        source="demo",
        event_type=FootballEventType.KICKOFF.value,
        subject_id="match-1",
        occurred_at=datetime(2026, 9, 12, 10, tzinfo=eastern),
        observed_at=datetime(2026, 9, 12, 10, tzinfo=eastern),
        version=1,
        dedupe_key="utc-check",
        correlation_id=uuid7(),
        payload={},
    )
    assert event.occurred_at == datetime(2026, 9, 12, 15, tzinfo=UTC)
    with pytest.raises(ValidationError):
        CanonicalEvent(
            source="demo",
            event_type=FootballEventType.KICKOFF.value,
            subject_id="match-1",
            occurred_at=datetime(2026, 9, 12, 10),
            observed_at=datetime.now(UTC),
            version=1,
            dedupe_key="naive-check",
            correlation_id=uuid7(),
            payload={},
        )
