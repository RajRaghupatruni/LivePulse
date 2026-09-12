from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://livepulse:livepulse@localhost:5432/livepulse"
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic: str = "livepulse.events.football.v1"
    kafka_consumer_group: str = "livepulse-projector-v1"
    service_name: str = "livepulse-api"
    demo_step_seconds: float = 6.0
    run_background_services: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
