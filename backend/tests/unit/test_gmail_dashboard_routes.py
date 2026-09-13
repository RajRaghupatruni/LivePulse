from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import Settings
from app.providers.gmail import router as gmail_routes


def test_dashboard_inbox_returns_compact_not_configured_state(monkeypatch) -> None:
    monkeypatch.setattr(gmail_routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1:5173")

    response = client.get("/api/v1/providers/gmail/messages?limit=4")

    assert response.status_code == 200
    assert response.json() == {"status": "not_configured", "configured": False, "messages": []}


def test_dashboard_message_detail_does_not_expose_body_or_unconfigured_mailbox(monkeypatch) -> None:
    monkeypatch.setattr(gmail_routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1:5173")

    response = client.get("/api/v1/providers/gmail/messages/message-1")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "message-1" not in response.text
