import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.websockets import WebSocketDisconnect

from app.api import routes
from app.core.config import RuntimeMode, Settings
from app.storage.database import get_session


def _demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "runtime_mode": RuntimeMode.PUBLIC_DEMO,
        "database_url": "postgresql+asyncpg://livepulse:local@personal-db:5432/livepulse",
        "public_demo_database_url": (
            "postgresql+asyncpg://livepulse_public_demo:demo@demo-db:5432/livepulse_public_demo"
        ),
        "public_demo_allowed_hosts": ("demo.example.test", "localhost"),
        "public_demo_allowed_origins": (
            "https://demo.example.test",
            "http://localhost:5174",
        ),
    }
    values.update(overrides)
    return Settings(**values)


def test_personal_local_rejects_unsupported_hosts_and_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    client = TestClient(routes.app, base_url="http://localhost")

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/live", headers={"host": "192.168.1.25:8000"}).status_code == 400
    assert (
        client.get(
            "/health/live",
            headers={"origin": "https://attacker.example", "host": "localhost"},
        ).status_code
        == 403
    )


def test_personal_local_allows_exact_loopback_http_and_websocket_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1:8000")

    response = client.get("/health/live", headers={"origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200

    with client.websocket_connect(
        "/ws",
        headers={
            "host": "127.0.0.1:8000",
            "origin": "http://127.0.0.1:5173",
        },
    ):
        pass


def test_personal_local_websocket_rejects_untrusted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1")

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws", headers={"host": "192.168.1.25:8000"}):
            pass
    assert closed.value.code == 1008


def test_personal_local_websocket_rejects_remote_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1")

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws", headers={"origin": "https://attacker.example"}):
            pass
    assert closed.value.code == 1008


def test_personal_local_rejects_loopback_origins_on_unlisted_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(routes.app, base_url="http://127.0.0.1:8000")

    assert (
        client.get("/health/live", headers={"origin": "http://127.0.0.1:5175"}).status_code
        == 403
    )
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:5175"}):
            pass
    assert closed.value.code == 1008


def test_public_demo_discards_personal_provider_configuration_and_uses_separate_database() -> None:
    settings = _demo_settings(
        api_football_key=SecretStr("real-looking-football-secret"),
        spotify_client_id="real-looking-client",
        spotify_client_secret=SecretStr("real-looking-spotify-secret"),
        spotify_redirect_uri="http://localhost/callback",
        github_owner="raj-private",
        github_token=SecretStr("real-looking-github-token"),
        github_webhook_secret=SecretStr("real-looking-webhook-secret"),
        google_client_id="real-looking-google-client",
        google_client_secret=SecretStr("real-looking-google-secret"),
        google_redirect_uri="http://localhost/callback",
        weather_latitude=41.9,
        weather_longitude=-87.6,
        weather_timezone="America/Chicago",
        credential_encryption_key=SecretStr("personal-key-material"),
    )

    assert settings.runtime_database_url == settings.public_demo_database_url
    assert settings.provider_configuration() == {
        "football": False,
        "spotify": False,
        "github": False,
        "gmail": False,
        "weather": False,
    }
    assert settings.api_football_key is None
    assert settings.spotify_client_secret is None
    assert settings.github_token is None
    assert settings.google_client_secret is None
    assert settings.weather_latitude is None
    assert settings.credential_encryption_key is None
    assert "real-looking" not in repr(settings)


def test_public_demo_fails_closed_without_isolated_database_or_exact_allowlists() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_DEMO requires PUBLIC_DEMO_DATABASE_URL"):
        Settings(_env_file=None, runtime_mode=RuntimeMode.PUBLIC_DEMO)

    with pytest.raises(ValidationError, match="dedicated database role"):
        _demo_settings(
            public_demo_database_url=(
                "postgresql+asyncpg://livepulse:other@demo-db:5432/livepulse_public_demo"
            )
        )

    with pytest.raises(ValidationError, match="wildcards"):
        _demo_settings(public_demo_allowed_origins=("*",))


def test_public_demo_health_disables_all_real_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "get_settings", _demo_settings)

    providers = asyncio.run(routes._provider_health_snapshot())

    assert all(item["configured"] is False for item in providers.values())
    assert all(item["connected"] is False for item in providers.values())
    assert {item["detail_code"] for item in providers.values()} == {"disabled_in_public_demo"}


def test_public_demo_provider_routes_are_not_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _demo_settings()
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    client = TestClient(routes.app, base_url="http://localhost:5174")

    assert client.get("/api/v1/providers/spotify/oauth/start").status_code == 404
    assert client.get("/api/v1/providers/gmail/oauth/start").status_code == 404
    assert client.post("/api/v1/webhooks/github", content=b"{} ").status_code == 404
    assert client.get("/api/v1/football/fixtures").status_code == 404


def test_public_demo_state_and_timeline_read_only_the_isolated_demo_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _demo_settings(run_background_services=False)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    class EmptyDemoSession:
        async def get(self, *_args: object) -> None:
            return None

        async def scalar(self, *_args: object) -> None:
            return None

        async def scalars(self, *_args: object) -> list[object]:
            return []

        async def execute(self, *_args: object) -> list[object]:
            return []

    async def demo_database_session():
        # The actual runtime database selector must never fall back to the personal URL.
        assert settings.runtime_database_url == settings.public_demo_database_url
        yield EmptyDemoSession()

    previous = routes.app.dependency_overrides.get(get_session)
    routes.app.dependency_overrides[get_session] = demo_database_session
    try:
        client = TestClient(routes.app, base_url="http://localhost:5174")
        state = client.get("/api/v1/live-state").json()
        timeline = client.get("/api/v1/timeline").json()

        assert state["match"] is None
        assert timeline["items"] == []
        assert timeline["latest_cursor"] == 0
    finally:
        if previous is None:
            routes.app.dependency_overrides.pop(get_session, None)
        else:
            routes.app.dependency_overrides[get_session] = previous


def test_public_demo_application_registry_never_registers_real_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _demo_settings(
        run_background_services=False,
        api_football_key=SecretStr("football-key"),
        spotify_client_id="client",
        spotify_client_secret=SecretStr("secret"),
        spotify_redirect_uri="http://localhost/callback",
        github_owner="personal",
        github_token=SecretStr("token"),
        google_client_id="google-client",
        google_client_secret=SecretStr("google-secret"),
        google_redirect_uri="http://localhost/callback",
        weather_latitude=42.0,
        weather_longitude=-87.0,
        weather_timezone="America/Chicago",
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(routes, "engine", FakeEngine())
    with TestClient(routes.app, base_url="http://localhost:5174"):
        registry = routes.app.state.provider_registry
        assert registry.poll_sources == ()
        assert registry.webhook_source("github") is None
        assert registry.command_target("spotify") is None
        assert routes.app.state.runtime_mode == "PUBLIC_DEMO"


def test_purge_can_blank_ignored_provider_configuration_without_touching_core_settings() -> None:
    from app.maintenance.purge import clear_local_provider_config_file

    env_file = Path.cwd() / ".provider-purge-unit-test.env"
    try:
        env_file.write_text(
            "DATABASE_URL=postgresql://local/db\n"
            "LIVEPULSE_MODE=PERSONAL_LOCAL\n"
            "API_FOOTBALL_KEY=football-secret\n"
            "WEATHER_LATITUDE=41.9\n"
            "WEATHER_LONGITUDE=-87.6\n"
            "OTHER_SETTING=preserve-me\n",
            encoding="utf-8",
        )

        assert clear_local_provider_config_file(env_file) is True
        cleaned = env_file.read_text(encoding="utf-8")
        assert "football-secret" not in cleaned
        assert "41.9" not in cleaned
        assert "-87.6" not in cleaned
        assert "DATABASE_URL=postgresql://local/db" in cleaned
        assert "LIVEPULSE_MODE=PERSONAL_LOCAL" in cleaned
        assert "OTHER_SETTING=preserve-me" in cleaned
    finally:
        env_file.unlink(missing_ok=True)
