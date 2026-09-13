from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api import routes
from app.domain.attention import DominantFocus, select_dominant_focus
from app.domain.focus import focus_for_match


def signal(
    priority: int,
    *,
    domain: str = "football",
    reason: str = "live_match",
    observed_at: datetime | None = None,
    subject_id: str | None = None,
) -> DominantFocus:
    created = observed_at or datetime(2026, 9, 13, tzinfo=UTC)
    return DominantFocus(
        priority=priority,
        domain=domain,  # type: ignore[arg-type]
        reason=reason,
        subject_id=subject_id,
        event_id=None,
        transient=priority >= 80,
        created_at=created,
        observed_at=created,
        expires_at=created + timedelta(seconds=12) if priority >= 80 else None,
    )


def test_dominant_focus_uses_server_priority_then_evidence_time() -> None:
    mail = signal(85, domain="gmail", reason="important_mail")
    goal = signal(100, reason="goal")
    assert select_dominant_focus([mail, goal]) == goal

    older = signal(80, domain="github", reason="ci_failure")
    newer = signal(
        80,
        domain="github",
        reason="ci_failure",
        observed_at=older.observed_at + timedelta(seconds=1),
    )
    assert select_dominant_focus([older, newer]) == newer


def test_dominant_focus_ties_are_stable_and_empty_candidates_stay_empty() -> None:
    github = signal(65, domain="system", reason="provider_degraded", subject_id="github")
    spotify = signal(65, domain="system", reason="provider_degraded", subject_id="spotify")
    assert select_dominant_focus([spotify, github]) == select_dominant_focus([github, spotify])
    assert select_dominant_focus([]) is None


def test_attention_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        signal(85, domain="gmail", observed_at=datetime(2026, 9, 13))


@pytest.mark.asyncio
async def test_live_state_attention_uses_recent_canonical_mail_and_provider_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(UTC)
    event = SimpleNamespace(
        event_type="mail.message.received",
        payload={"important": True},
        subject_id="thread-1",
        event_id=uuid4(),
        occurred_at=observed_at,
    )

    class Session:
        async def execute(self, _query: object) -> list[tuple[SimpleNamespace, datetime]]:
            return [(event, observed_at)]

    monkeypatch.setattr(routes, "get_settings", lambda: None)
    monkeypatch.setattr(
        routes.provider_health,
        "snapshot",
        lambda _settings: {
            "weather": {
                "configured": True,
                "status": "stale",
                "last_failure_at": observed_at.isoformat(),
            }
        },
    )

    dominant = await routes._dominant_focus(  # type: ignore[arg-type]
        Session(), None, focus_for_match("idle", None)
    )

    assert dominant is not None
    assert dominant.domain == "gmail"
    assert dominant.priority == 85
    assert dominant.subject_id == "thread-1"
    assert dominant.transient is True
    assert dominant.expires_at == observed_at + timedelta(seconds=12)


@pytest.mark.asyncio
async def test_expired_mail_does_not_outlive_persistent_degraded_provider_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(UTC) - timedelta(minutes=1)
    event = SimpleNamespace(
        event_type="mail.message.received",
        payload={"important": True},
        subject_id="thread-1",
        event_id=uuid4(),
        occurred_at=observed_at,
    )

    class Session:
        async def execute(self, _query: object) -> list[tuple[SimpleNamespace, datetime]]:
            return [(event, observed_at)]

    monkeypatch.setattr(routes, "get_settings", lambda: None)
    monkeypatch.setattr(
        routes.provider_health,
        "snapshot",
        lambda _settings: {
            "weather": {
                "configured": True,
                "status": "stale",
                "last_failure_at": observed_at.isoformat(),
            }
        },
    )

    dominant = await routes._dominant_focus(  # type: ignore[arg-type]
        Session(), None, focus_for_match("idle", None)
    )

    assert dominant is not None
    assert dominant.domain == "system"
    assert dominant.subject_id == "weather"
    assert dominant.priority == 65
    assert dominant.transient is False
