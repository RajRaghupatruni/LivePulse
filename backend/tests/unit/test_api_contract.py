from fastapi.testclient import TestClient

from app.api.routes import app


def test_required_api_and_websocket_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert {
        "/health/live",
        "/health/ready",
        "/api/v1/live-state",
        "/api/v1/timeline",
        "/api/v1/system/health",
        "/api/v1/webhooks/github",
        "/api/v1/providers/github/health",
        "/api/v1/providers/weather/current",
        "/api/v1/providers/weather/health",
        "/api/v1/providers/gmail/connection",
    } <= paths
    assert "/ws" in {getattr(route, "path", None) for route in app.routes}


def test_api_errors_share_a_stable_envelope_and_request_id() -> None:
    client = TestClient(app, base_url="http://localhost")
    missing = client.get("/not-a-livepulse-route", headers={"x-request-id": "audit-request"})
    invalid = client.get("/api/v1/timeline?limit=999", headers={"x-request-id": "audit-validation"})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert missing.json()["error"]["request_id"] == "audit-request"
    assert missing.headers["x-request-id"] == "audit-request"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["request_id"] == "audit-validation"
