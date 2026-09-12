from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://livepulse:livepulse@localhost:5432/livepulse"
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic: str = "livepulse.events.football.v1"
    kafka_consumer_group: str = "livepulse-projector-v1"
    service_name: str = "livepulse-api"
    demo_step_seconds: float = 6.0
    run_background_services: bool = True

    # Optional provider configuration. Missing values must never block app startup.
    api_football_key: SecretStr | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: SecretStr | None = None
    spotify_redirect_uri: str | None = None
    github_token: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    github_repositories: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["Strata", "Tandem", "OptiScale", "LivePulse", "Portfolio"]
    )
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    weather_latitude: float | None = Field(default=None, ge=-90, le=90)
    weather_longitude: float | None = Field(default=None, ge=-180, le=180)
    weather_timezone: str | None = None
    credential_encryption_key: SecretStr | None = None

    @field_validator("weather_latitude", "weather_longitude", mode="before")
    @classmethod
    def blank_weather_coordinates_are_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("github_repositories", mode="before")
    @classmethod
    def parse_github_repositories(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [name.strip() for name in value.split(",") if name.strip()]
        if isinstance(value, list):
            return [str(name).strip() for name in value if str(name).strip()]
        raise ValueError("GITHUB_REPOSITORIES must be a comma-separated string")

    def provider_configuration(self) -> dict[str, bool]:
        """Report configuration completeness without exposing credential values."""

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
            "github": bool(self.github_repositories)
            and has(self.github_token)
            and has(self.github_webhook_secret),
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
