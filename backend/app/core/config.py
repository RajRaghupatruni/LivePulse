import re
from enum import StrEnum
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MONITORED_GITHUB_REPOSITORIES = (
    "Strata",
    "Tandem",
    "OptiScale",
    "LivePulse",
    "Portfolio",
)
LOCKED_GITHUB_REPOSITORIES = frozenset(name.casefold() for name in MONITORED_GITHUB_REPOSITORIES)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class RuntimeMode(StrEnum):
    PERSONAL_LOCAL = "PERSONAL_LOCAL"
    PUBLIC_DEMO = "PUBLIC_DEMO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    runtime_mode: RuntimeMode = Field(
        default=RuntimeMode.PERSONAL_LOCAL, validation_alias="LIVEPULSE_MODE"
    )
    database_url: str = Field(
        default="postgresql+asyncpg://livepulse:livepulse@localhost:5432/livepulse",
        repr=False,
    )
    public_demo_database_url: str | None = Field(default=None, repr=False)
    public_demo_allowed_hosts: tuple[str, ...] = ()
    public_demo_allowed_origins: tuple[str, ...] = ()
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic: str = "livepulse.events.football.v1"
    kafka_consumer_group: str = "livepulse-projector-v1"
    service_name: str = "livepulse-api"
    frontend_base_url: str = Field(
        default="http://127.0.0.1:5173", validation_alias="FRONTEND_BASE_URL"
    )
    demo_step_seconds: float = 6.0
    run_background_services: bool = True

    # Optional provider configuration. Missing values must never block app startup.
    api_football_key: SecretStr | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: SecretStr | None = None
    spotify_redirect_uri: str | None = None
    github_owner: str | None = None
    github_token: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    github_webhook_allowed_hosts: tuple[str, ...] = ()
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    weather_latitude: float | None = Field(default=None, ge=-90, le=90)
    weather_longitude: float | None = Field(default=None, ge=-180, le=180)
    weather_timezone: str | None = None
    credential_encryption_key: SecretStr | None = None
    retention_days: int = Field(default=365, ge=30, le=3650)

    @field_validator(
        "public_demo_allowed_hosts",
        "public_demo_allowed_origins",
        "github_webhook_allowed_hosts",
        mode="before",
    )
    @classmethod
    def parse_allowlist(cls, value: object) -> object:
        if isinstance(value, str):
            # Environment values are intentionally JSON arrays, not wildcard/CSV shortcuts.
            import json

            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("allowlists must be JSON arrays") from exc
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("allowlists must be arrays")
        return tuple(str(item).strip() for item in value)

    @field_validator("github_webhook_allowed_hosts")
    @classmethod
    def validate_github_webhook_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        hosts: list[str] = []
        for item in value:
            host = item.casefold().rstrip(".")
            labels = host.split(".")
            if (
                not host
                or len(host) > 253
                or any(not label.isascii() or not _HOST_LABEL.fullmatch(label) for label in labels)
            ):
                raise ValueError("GitHub webhook allowed hosts must be exact hostnames")
            hosts.append(host)
        return tuple(hosts)

    @field_validator("weather_latitude", "weather_longitude", mode="before")
    @classmethod
    def blank_weather_coordinates_are_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def enforce_runtime_mode_boundaries(self) -> "Settings":
        if self.runtime_mode is RuntimeMode.PUBLIC_DEMO:
            if not self.public_demo_database_url:
                raise ValueError("PUBLIC_DEMO requires PUBLIC_DEMO_DATABASE_URL")
            if not self.public_demo_allowed_hosts or not self.public_demo_allowed_origins:
                raise ValueError("PUBLIC_DEMO requires explicit host and origin allowlists")
            if any(
                "*" in item
                for item in (*self.public_demo_allowed_hosts, *self.public_demo_allowed_origins)
            ):
                raise ValueError("PUBLIC_DEMO allowlists cannot contain wildcards")
            for origin in self.public_demo_allowed_origins:
                parsed = urlsplit(origin)
                try:
                    _ = parsed.port
                except ValueError as exc:
                    raise ValueError("PUBLIC_DEMO origins must be exact HTTP(S) origins") from exc
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError("PUBLIC_DEMO origins must be exact HTTP(S) origins")
            for host in self.public_demo_allowed_hosts:
                try:
                    parsed_host = urlsplit("//" + host)
                    valid_host = (
                        bool(parsed_host.hostname)
                        and not parsed_host.path
                        and not parsed_host.query
                        and not parsed_host.fragment
                        and parsed_host.username is None
                    )
                    _ = parsed_host.port
                except ValueError:
                    valid_host = False
                if not valid_host:
                    raise ValueError("PUBLIC_DEMO hosts must be exact host names")
            personal = urlsplit(self.database_url)
            demo = urlsplit(self.public_demo_database_url)
            if (
                demo.scheme not in {"postgresql", "postgresql+asyncpg"}
                or not demo.hostname
                or not demo.path.strip("/")
                or not demo.username
            ):
                raise ValueError("PUBLIC_DEMO database URL must identify a database and role")
            if (personal.username or "").casefold() == demo.username.casefold():
                raise ValueError("PUBLIC_DEMO database must use a dedicated database role")
            if personal.path.strip("/").casefold() == demo.path.strip("/").casefold():
                raise ValueError("PUBLIC_DEMO database name must differ from the personal database")

            # Provider configuration is intentionally discarded in demo mode. This prevents
            # accidental source registration even if a personal .env was copied alongside it.
            for field_name in (
                "api_football_key",
                "spotify_client_id",
                "spotify_client_secret",
                "spotify_redirect_uri",
                "github_owner",
                "github_token",
                "github_webhook_secret",
                "google_client_id",
                "google_client_secret",
                "google_redirect_uri",
                "weather_latitude",
                "weather_longitude",
                "weather_timezone",
                "credential_encryption_key",
            ):
                setattr(self, field_name, None)
            self.github_webhook_allowed_hosts = ()
        return self

    @property
    def runtime_database_url(self) -> str:
        if self.runtime_mode is RuntimeMode.PUBLIC_DEMO:
            # Validation above makes this a required, isolated database. Never fall back.
            assert self.public_demo_database_url is not None
            return self.public_demo_database_url
        return self.database_url

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        if self.runtime_mode is RuntimeMode.PUBLIC_DEMO:
            return self.public_demo_allowed_origins
        return ("http://localhost:5173", "http://127.0.0.1:5173")

    def __repr__(self) -> str:
        return f"Settings(runtime_mode={self.runtime_mode.value!r}, database_url=<redacted>)"

    def provider_configuration(self) -> dict[str, bool]:
        """Report configuration completeness without exposing credential values."""

        if self.runtime_mode is RuntimeMode.PUBLIC_DEMO:
            return {
                provider: False
                for provider in ("football", "spotify", "github", "gmail", "weather")
            }

        def has(value: str | SecretStr | None) -> bool:
            raw = value.get_secret_value() if isinstance(value, SecretStr) else value
            return bool(raw and raw.strip()) if isinstance(raw, str) else bool(raw)

        return {
            "football": has(self.api_football_key),
            "spotify": all(
                has(value)
                for value in (
                    self.spotify_client_id,
                    self.spotify_client_secret,
                    self.spotify_redirect_uri,
                )
            ),
            "github": has(self.github_owner)
            and (has(self.github_token) or has(self.github_webhook_secret)),
            "gmail": all(
                has(value)
                for value in (
                    self.google_client_id,
                    self.google_client_secret,
                    self.google_redirect_uri,
                )
            ),
            "weather": all(
                value is not None
                for value in (
                    self.weather_latitude,
                    self.weather_longitude,
                )
            )
            and bool(self.weather_timezone and self.weather_timezone.strip()),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
