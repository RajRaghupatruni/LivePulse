from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import routes


class FakeSession:
    def __init__(self, latest: int, rows: list[object]) -> None:
        self.latest = latest
        self.rows = rows

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, _query: object) -> int:
        return self.latest

    async def scalars(self, _query: object) -> list[object]:
        return self.rows

    async def execute(self, _query: object) -> list[object]:
        return self.rows


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)
        raise WebSocketDisconnect(code=1000)


@pytest.mark.asyncio
async def test_reconnect_replays_durable_items_after_last_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        cursor=4,
        event_id=uuid4(),
        event_type="football.match.goal",
        source="demo-football",
        subject_id="match-1",
        occurred_at=datetime.now(UTC),
        payload={"side": "home"},
    )
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(routes, "SessionFactory", lambda: FakeSession(4, [(row, observed_at)]))
    websocket = FakeWebSocket()

    await routes.websocket_endpoint(websocket, last_cursor=3)  # type: ignore[arg-type]

    assert websocket.messages == [
        {
            "type": "timeline.item",
            "cursor": 4,
            "event_id": str(row.event_id),
            "event_type": "football.match.goal",
            "source": "demo-football",
            "subject_id": "match-1",
            "timestamp": row.occurred_at.isoformat(),
            "observed_at": observed_at.isoformat(),
            "payload": {"side": "home"},
            "replayed": True,
        }
    ]


@pytest.mark.asyncio
async def test_ahead_cursor_requests_authoritative_resync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "SessionFactory", lambda: FakeSession(4, []))
    websocket = FakeWebSocket()

    await routes.websocket_endpoint(websocket, last_cursor=9)  # type: ignore[arg-type]

    assert websocket.messages == [
        {"type": "resync_required", "reason": "cursor_ahead", "latest_cursor": 4}
    ]
