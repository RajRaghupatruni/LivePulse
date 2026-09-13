import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.config import MONITORED_GITHUB_REPOSITORIES, Settings, get_settings
from app.providers.base import PollContext, PollSchedule
from app.providers.commands import CommandRequest, CommandResult
from app.providers.credentials import (
    CredentialCipher,
    CredentialEncryptionError,
    EncryptedCredentials,
)
from app.providers.observations import Observation
from app.providers.registry import ProviderRegistry
from app.providers.scheduler import PollScheduler, RetryAfterError, next_poll_delay
from app.providers.status import ProviderHealthRegistry
from app.storage.models import Base, ProviderConnectionRow


class DemoContent(BaseModel):
    count: int


class FakePollSource:
    def __init__(self, provider_id: str, observe) -> None:
        self.provider_id = provider_id
        self.schedule = PollSchedule(
            interval=timedelta(milliseconds=10),
            timeout=timedelta(seconds=1),
            max_backoff=timedelta(seconds=2),
            jitter_ratio=0,
        )
        self._observe = observe

    def cadence(self, *, context: PollContext) -> timedelta:
        return timedelta(milliseconds=10)

    async def observe(self, *, context: PollContext):
        return await self._observe(context)


def test_provider_observation_is_typed_utc_and_immutable() -> None:
    observation = Observation[DemoContent](
        provider_id="weather",
        external_entity_id="grid-cell-17",
        observed_at=datetime(2026, 9, 12, 10, tzinfo=UTC),
        content=DemoContent(count=3),
        provider_version="revision-4",
        checkpoint="cursor-4",
    )
    assert observation.content.count == 3
    assert observation.observed_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        observation.provider_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Observation[DemoContent](
            provider_id="weather",
            external_entity_id="grid-cell-17",
            observed_at=datetime(2026, 9, 12),
            content=DemoContent(count=3),
        )


def test_optional_provider_settings_do_not_block_boot_and_repositories_parse() -> None:
    settings = Settings(_env_file=None)
    assert settings.provider_configuration() == {
        "football": False,
        "spotify": False,
        "github": False,
        "gmail": False,
        "weather": False,
    }
    assert MONITORED_GITHUB_REPOSITORIES == (
        "Strata",
        "Tandem",
        "OptiScale",
        "LivePulse",
        "Portfolio",
    )
    assert (
        Settings(_env_file=None, api_football_key="   ").provider_configuration()["football"]
        is False
    )


@pytest.mark.parametrize("field", ["weather_latitude", "weather_longitude"])
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_weather_coordinates_normalize_to_none(field: str, blank: str) -> None:
    assert getattr(Settings(_env_file=None, **{field: blank}), field) is None


def test_weather_coordinates_default_to_none_and_parse_valid_numbers() -> None:
    missing = Settings(_env_file=None)
    assert missing.weather_latitude is None
    assert missing.weather_longitude is None

    configured = Settings(
        _env_file=None,
        weather_latitude="41.8781",
        weather_longitude="-87.6298",
    )
    assert configured.weather_latitude == 41.8781
    assert isinstance(configured.weather_latitude, float)
    assert configured.weather_longitude == -87.6298
    assert isinstance(configured.weather_longitude, float)


@pytest.mark.parametrize(
    ("field", "value"),
    [("weather_latitude", "north"), ("weather_longitude", "west")],
)
def test_invalid_nonblank_weather_coordinate_still_fails(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_settings_startup_accepts_blank_weather_values_from_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEATHER_LATITUDE", raising=False)
    monkeypatch.delenv("WEATHER_LONGITUDE", raising=False)
    env_file = Path(__file__).resolve().parents[3] / ".env.example"
    settings = Settings(_env_file=env_file)

    assert settings.weather_latitude is None
    assert settings.weather_longitude is None
    assert settings.provider_configuration()["weather"] is False


def test_application_settings_startup_accepts_blank_weather_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEATHER_LATITUDE", "")
    monkeypatch.setenv("WEATHER_LONGITUDE", "   ")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.weather_latitude is None
        assert settings.weather_longitude is None
    finally:
        get_settings.cache_clear()


def test_provider_health_is_normalized_and_secret_free() -> None:
    registry = ProviderHealthRegistry()
    settings = Settings(_env_file=None, api_football_key="not-a-real-key")
    snapshots = registry.snapshot(settings)
    assert snapshots["football"]["status"] == "unknown"
    assert snapshots["football"]["configured"] is True
    assert snapshots["spotify"]["status"] == "disconnected"
    assert snapshots["spotify"]["detail_code"] == "configuration_missing"

    registry.failure("football", "temporary_failure")
    registry.failure("football", "temporary_failure")
    failed = registry.failure("football", "temporary_failure")
    assert failed.status == "unavailable"
    assert failed.consecutive_failures == 3
    recovered = registry.success("football", observed=True)
    assert recovered.status == "healthy"
    assert recovered.consecutive_failures == 0
    assert recovered.last_observation_at is not None
    assert "not-a-real-key" not in str(registry.snapshot(settings))


def test_capability_registry_keeps_provider_capabilities_explicit() -> None:
    async def observe(_context: PollContext):
        return ()

    source = FakePollSource("football", observe)
    registry = ProviderRegistry()
    registry.register_poll_source(source)
    assert registry.poll_sources == (source,)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_poll_source(source)
    with pytest.raises(ValueError, match="provider_id"):
        registry.register_poll_source(type("NoId", (), {})())  # type: ignore[arg-type]


def test_command_contract_validates_supported_spotify_arguments() -> None:
    seek = CommandRequest(command="spotify.seek", arguments={"position_seconds": 31})
    volume = CommandRequest(command="spotify.volume", arguments={"volume_percent": 80})
    transfer = CommandRequest(command="spotify.transfer_device", arguments={"device_id": "desk"})
    assert isinstance(seek.correlation_id, UUID)
    assert (
        seek.arguments.position_seconds,
        volume.arguments.volume_percent,
        transfer.arguments.device_id,
    ) == (
        31,
        80,
        "desk",
    )
    with pytest.raises(ValidationError, match="requires position_seconds"):
        CommandRequest(command="spotify.seek")
    with pytest.raises(ValidationError, match="does not accept arguments"):
        CommandRequest(command="spotify.play", arguments={"volume_percent": 30})
    with pytest.raises(ValidationError):
        CommandRequest(command="spotify.volume", arguments={"volume_percent": 101})
    with pytest.raises(ValidationError, match="require a stable error code"):
        CommandResult(success=False, provider="spotify", message="Unavailable")


def test_poll_delay_bounds_jitter_backoff_and_retry_after() -> None:
    interval = timedelta(seconds=10)
    cap = timedelta(seconds=30)
    assert next_poll_delay(
        interval=interval,
        failure_count=0,
        max_backoff=cap,
        jitter_ratio=0.2,
        random_value=0,
    ) == timedelta(seconds=8)
    assert next_poll_delay(
        interval=interval,
        failure_count=0,
        max_backoff=cap,
        jitter_ratio=0.2,
        random_value=1,
    ) == timedelta(seconds=12)
    assert (
        next_poll_delay(
            interval=interval,
            failure_count=10_000,
            max_backoff=cap,
            jitter_ratio=0.2,
            random_value=1,
        )
        == cap
    )
    assert next_poll_delay(
        interval=interval,
        failure_count=2,
        max_backoff=cap,
        jitter_ratio=0,
        random_value=0.5,
    ) == timedelta(seconds=20)
    now = datetime(2026, 9, 12, tzinfo=UTC)
    cooldown = now + timedelta(minutes=1)
    assert next_poll_delay(
        interval=interval,
        failure_count=1,
        max_backoff=cap,
        jitter_ratio=0,
        random_value=0.5,
        retry_after=cooldown,
        now=now,
    ) == timedelta(minutes=1)
    with pytest.raises(ValueError, match="timezone-aware"):
        RetryAfterError(datetime(2026, 9, 12))


@pytest.mark.asyncio
async def test_scheduler_bounds_concurrency_and_delivers_observations() -> None:
    active = 0
    peak = 0
    observed_count = 0
    two_running = asyncio.Event()
    released = asyncio.Event()
    delivered = asyncio.Event()

    async def make_observer(_context: PollContext):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            two_running.set()
        try:
            await released.wait()
            return (
                Observation[DemoContent](
                    provider_id="weather",
                    external_entity_id="station-1",
                    observed_at=datetime.now(UTC),
                    content=DemoContent(count=1),
                ),
            )
        finally:
            active -= 1

    async def handler(provider: str, observations, _context: PollContext) -> None:
        nonlocal observed_count
        assert provider.startswith("source-")
        observed_count += len(observations)
        delivered.set()

    sources = [FakePollSource(f"source-{i}", make_observer) for i in range(4)]
    scheduler = PollScheduler(sources, observation_handler=handler, max_concurrency=2)
    running = asyncio.create_task(scheduler.run())
    await asyncio.wait_for(two_running.wait(), timeout=1)
    assert peak == 2
    released.set()
    await asyncio.wait_for(delivered.wait(), timeout=1)
    await scheduler.stop()
    await asyncio.wait_for(running, timeout=1)
    assert peak <= 2
    assert observed_count >= 2


@pytest.mark.asyncio
async def test_scheduler_shutdown_cancels_inflight_poll_cleanly() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def observe(_context: PollContext):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def handler(_provider: str, _observations, _context: PollContext) -> None:
        return None

    scheduler = PollScheduler([FakePollSource("gmail", observe)], observation_handler=handler)
    running = asyncio.create_task(scheduler.run())
    await asyncio.wait_for(started.wait(), timeout=1)
    await scheduler.stop()
    await asyncio.wait_for(running, timeout=1)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_scheduler_times_out_a_slow_source_and_records_failure() -> None:
    health = ProviderHealthRegistry()

    async def observe(_context: PollContext):
        await asyncio.sleep(1)
        return ()

    async def handler(_provider: str, _observations, _context: PollContext) -> None:
        return None

    class SlowSource(FakePollSource):
        def cadence(self, *, context: PollContext) -> timedelta:
            return timedelta(seconds=60)

    source = SlowSource("weather", observe)
    source.schedule = PollSchedule(
        interval=timedelta(milliseconds=10),
        timeout=timedelta(milliseconds=10),
        max_backoff=timedelta(seconds=120),
        jitter_ratio=0,
    )
    scheduler = PollScheduler([source], observation_handler=handler, health=health)
    running = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0.03)
    await scheduler.stop()
    await asyncio.wait_for(running, timeout=1)
    state = health.snapshot(Settings(_env_file=None))["weather"]
    assert state["status"] in {"provider_failure", "unavailable"}
    assert state["consecutive_failures"] >= 1
    assert state["detail_code"] == "poll_timeout"


@pytest.mark.asyncio
async def test_scheduler_poll_now_uses_normal_observation_persistence_handler() -> None:
    delivered: list[Observation[DemoContent]] = []

    async def observe(context: PollContext):
        return (
            Observation[DemoContent](
                provider_id="weather",
                external_entity_id="selected-location",
                observed_at=context.scheduled_at,
                content=DemoContent(count=1),
                correlation_id=context.correlation_id,
            ),
        )

    async def handler(_provider: str, observations, _context: PollContext) -> None:
        delivered.extend(observations)

    health = ProviderHealthRegistry()
    scheduler = PollScheduler(
        [FakePollSource("weather", observe)],
        observation_handler=handler,
        health=health,
    )
    observations = await scheduler.poll_now("weather")
    assert len(observations) == len(delivered) == 1
    assert delivered[0].external_entity_id == "selected-location"
    assert health.snapshot(Settings(_env_file=None))["weather"]["status"] == "healthy"


def test_credential_cipher_and_database_column_reject_plaintext() -> None:
    key = Fernet.generate_key().decode("ascii")
    cipher = CredentialCipher(key)
    plaintext = '{"refresh_token":"highly-sensitive"}'
    encrypted = cipher.encrypt(plaintext)
    assert isinstance(encrypted, EncryptedCredentials)
    assert plaintext not in encrypted.token
    assert "highly-sensitive" not in repr(encrypted)
    assert cipher.decrypt(encrypted).decode() == plaintext
    with pytest.raises(CredentialEncryptionError, match="not configured"):
        CredentialCipher(None)
    with pytest.raises(ValueError, match="Fernet ciphertext"):
        EncryptedCredentials(plaintext)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ProviderConnectionRow(
                provider="spotify",
                status="connected",
                encrypted_credentials=encrypted,
                scopes=["user-read-playback-state"],
            )
        )
        session.commit()
        row = session.query(ProviderConnectionRow).one()
        assert cipher.decrypt(row.encrypted_credentials).decode() == plaintext
        stored = session.execute(
            text("SELECT encrypted_credentials FROM provider_connections WHERE provider='spotify'")
        ).scalar_one()
        assert stored != plaintext
        assert "highly-sensitive" not in stored

    with Session(engine) as session:
        session.add(
            ProviderConnectionRow(
                provider="gmail",
                encrypted_credentials=plaintext,  # type: ignore[arg-type]
            )
        )
        with pytest.raises((StatementError, TypeError), match="encrypted before persistence"):
            session.commit()
    engine.dispose()
