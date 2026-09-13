from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from uuid6 import uuid7

from app.domain.events import CanonicalEvent
from app.projections import projector
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    MatchStateRow,
    PulseTimelineRow,
)


class _AsyncContext:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, event: CanonicalEvent) -> None:
        self.event = event
        self.added: list[object] = []

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return _AsyncContext(self)

    async def get(self, model: type, _key: object) -> object | None:
        if model is CanonicalEventRow:
            return self.event
        if model is ConsumerProcessedEventRow:
            return None
        raise AssertionError("non-football provider events must not access match state")

    def add(self, row: object) -> None:
        self.added.append(row)
        if isinstance(row, PulseTimelineRow):
            row.cursor = 17

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_nonfootball_canonical_event_projects_to_timeline_without_match_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = CanonicalEvent(
        source="github",
        event_type="developer.workflow.failed",
        subject_type="workflow_run",
        subject_id="acme/Strata#RUN-44",
        occurred_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        version=1,
        dedupe_key="github:acme/strata:workflow:44:failure",
        correlation_id=uuid7(),
        payload={"repository": "acme/Strata", "workflow": "CI", "conclusion": "failure"},
    )
    session = _Session(event)

    class _SessionFactory:
        def __call__(self) -> _Session:
            return session

    notifications: list[dict[str, object]] = []

    async def publish(message: dict[str, object]) -> None:
        notifications.append(message)

    monkeypatch.setattr(projector, "SessionFactory", _SessionFactory())
    monkeypatch.setattr(projector.realtime, "publish", publish)

    assert await projector.process_canonical_event(event) is True
    assert any(isinstance(row, ConsumerProcessedEventRow) for row in session.added)
    assert any(isinstance(row, PulseTimelineRow) for row in session.added)
    assert not any(isinstance(row, MatchStateRow) for row in session.added)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification["event_type"] == "developer.workflow.failed"
    assert notification["subject_id"] == event.subject_id
    assert "state" not in notification
    assert notification["focus"]["source"] == "github"
