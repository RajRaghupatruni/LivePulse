from app.api.routes import app


def test_required_api_and_websocket_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert {
        "/health/live",
        "/health/ready",
        "/api/v1/live-state",
        "/api/v1/timeline",
    } <= paths
    assert "/ws" in {getattr(route, "path", None) for route in app.routes}
