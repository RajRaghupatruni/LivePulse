from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import routes
from app.core.config import Settings
from app.core.health import _components, component_snapshot, overall_status, report_component
from app.providers.status import ProviderHealthRegistry


def test_application_boots_with_no_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, run_background_services=False)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(routes, "engine", FakeEngine())
    with TestClient(routes.app, base_url="http://localhost") as client:
        assert client.get("/health/live").json() == {"status": "live"}
        registry = routes.app.state.provider_registry
        assert tuple(source.provider_id for source in registry.poll_sources) == ("weather",)
        assert registry.command_target("spotify") is not None
        assert client.get("/api/v1/football/fixtures").status_code == 200
        assert client.post("/api/v1/webhooks/github", content=b"{}").status_code == 401
        assert client.get("/api/v1/providers/spotify/oauth/start").status_code == 503
        assert client.get("/api/v1/providers/gmail/oauth/start").status_code == 503
        assert client.get("/api/v1/providers/weather/current").status_code == 200


def test_configured_providers_are_registered_without_startup_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        run_background_services=False,
        api_football_key=SecretStr("football-key"),
        spotify_client_id="spotify-client",
        spotify_client_secret=SecretStr("spotify-secret"),
        spotify_redirect_uri=("http://127.0.0.1:8000/api/v1/providers/spotify/oauth/callback"),
        github_owner="acme",
        github_token=SecretStr("github-token"),
        github_webhook_secret=SecretStr("github-webhook-secret"),
        google_client_id="google-client",
        google_client_secret=SecretStr("google-secret"),
        google_redirect_uri="http://localhost:8000/api/v1/providers/gmail/oauth/callback",
        weather_latitude=41.9,
        weather_longitude=-87.6,
        weather_timezone="America/Chicago",
        credential_encryption_key=SecretStr(Fernet.generate_key().decode("ascii")),
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(routes, "engine", FakeEngine())
    with TestClient(routes.app):
        registry = routes.app.state.provider_registry
        assert {source.provider_id for source in registry.poll_sources} == {
            "football",
            "github",
            "spotify",
            "gmail",
            "weather",
        }
        assert registry.webhook_source("github") is not None
        assert registry.command_target("spotify") is not None


def test_health_aggregation_never_promotes_unknown_or_failed_dependencies() -> None:
    assert overall_status({"postgres": {"status": "unknown"}}) == "unknown"
    assert (
        overall_status({"postgres": {"status": "healthy"}, "projector": {"status": "degraded"}})
        == "degraded"
    )
    assert (
        overall_status({"postgres": {"status": "unavailable"}, "redpanda": {"status": "healthy"}})
        == "unavailable"
    )


def test_worker_health_becomes_degraded_when_heartbeat_goes_stale() -> None:
    _components["projector"] = {
        "name": "projector",
        "status": "healthy",
        "detail": "poll_complete",
        "checked_at": (datetime.now(UTC) - timedelta(seconds=11)).isoformat(),
        "last_success_at": None,
    }

    assert component_snapshot("projector")["status"] == "degraded"
    assert component_snapshot("projector")["detail"] == "heartbeat_stale"


@pytest.mark.asyncio
async def test_configured_oauth_without_encryption_key_reports_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        spotify_client_id="spotify-client",
        spotify_client_secret="spotify-secret",
        spotify_redirect_uri="http://localhost:8000/api/v1/providers/spotify/oauth/callback",
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="http://localhost:8000/api/v1/providers/gmail/oauth/callback",
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "provider_health", ProviderHealthRegistry())

    class EmptySession:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def scalar(self, _query: object) -> None:
            return None

    monkeypatch.setattr(routes, "SessionFactory", EmptySession)

    providers = await routes._provider_health_snapshot()

    assert providers["spotify"]["configured"] is True
    assert providers["spotify"]["status"] == "degraded"
    assert providers["spotify"]["detail_code"] == "credential_encryption_unavailable"
    assert providers["gmail"]["configured"] is True
    assert providers["gmail"]["status"] == "degraded"
    assert providers["gmail"]["detail_code"] == "credential_encryption_unavailable"


@pytest.mark.asyncio
async def test_system_health_reports_unavailable_postgres_without_hiding_worker_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def postgres_failure() -> dict[str, Any]:
        report_component("postgres", "unavailable", "connection_failed")
        return component_snapshot("postgres")

    async def broker_ok() -> dict[str, Any]:
        report_component("redpanda", "healthy", "broker_connected", succeeded=True)
        return component_snapshot("redpanda")

    monkeypatch.setattr(routes, "_probe_postgres", postgres_failure)
    monkeypatch.setattr(routes, "_probe_redpanda", broker_ok)
    report_component("outbox_publisher", "unknown", "not_observed")
    report_component("projector", "healthy", "poll_complete", succeeded=True)
    report_component("demo_source", "healthy", "idle")

    result = await routes.system_health()

    assert result["status"] == "unavailable"
    assert result["components"]["postgres"]["status"] == "unavailable"
    assert result["components"]["redpanda"]["status"] == "healthy"
    assert result["components"]["outbox_publisher"]["status"] == "unknown"
    assert result["components"]["projector"]["status"] == "healthy"
    assert "connected_clients" in result["components"]["realtime"]["metrics"]
    assert set(result["providers"]) == {"football", "spotify", "github", "gmail", "weather"}
    assert result["providers"]["spotify"]["provider"] == "spotify"
