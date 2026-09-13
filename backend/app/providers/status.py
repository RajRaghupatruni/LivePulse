"""Secret-free, normalized provider health snapshots."""

from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import Settings, get_settings

ProviderStatusCode = Literal[
    "healthy",
    "degraded",
    "stale",
    "connecting",
    "resyncing",
    "rate_limited",
    "auth_failure",
    "provider_failure",
    "unavailable",
    "disconnected",
    "unknown",
]
PROVIDER_IDS = ("football", "spotify", "github", "gmail", "weather")


class ProviderHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,49}$")
    status: ProviderStatusCode
    configured: bool
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_observation_at: datetime | None = None
    last_message_observation_at: datetime | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    rate_limited_until: datetime | None = None
    detail_code: str = Field(pattern=r"^[a-z0-9_.-]{1,64}$")

    @field_validator(
        "checked_at",
        "last_success_at",
        "last_failure_at",
        "last_observation_at",
        "last_message_observation_at",
        "rate_limited_until",
    )
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("provider health timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return None


class ProviderHealthRegistry:
    """Single-process health state; a future multi-instance design can replace its storage."""

    def __init__(self) -> None:
        self._states: dict[str, ProviderHealth] = {}
        self._lock = RLock()

    def report(
        self,
        provider: str,
        status: ProviderStatusCode,
        detail_code: str,
        *,
        configured: bool = True,
        succeeded: bool = False,
        observed: bool = False,
        failed: bool = False,
        rate_limited_until: datetime | None = None,
        last_message_observation_at: datetime | None = None,
    ) -> ProviderHealth:
        now = datetime.now(UTC)
        with self._lock:
            previous = self._states.get(provider)
            failure_count = (previous.consecutive_failures if previous else 0) + 1 if failed else 0
            state = ProviderHealth(
                provider=provider,
                status=status,
                configured=configured,
                checked_at=now,
                last_success_at=now
                if succeeded
                else (previous.last_success_at if previous else None),
                last_failure_at=now if failed else (previous.last_failure_at if previous else None),
                last_observation_at=now
                if observed
                else (previous.last_observation_at if previous else None),
                last_message_observation_at=last_message_observation_at
                if last_message_observation_at is not None
                else (previous.last_message_observation_at if previous else None),
                consecutive_failures=failure_count,
                rate_limited_until=rate_limited_until,
                detail_code=detail_code,
            )
            self._states[provider] = state
            return state

    def success(
        self, provider: str, *, observed: bool = False, configured: bool = True
    ) -> ProviderHealth:
        if not configured:
            return self.report(
                provider,
                "disconnected",
                "configuration_missing",
                configured=False,
                observed=False,
            )
        return self.report(
            provider,
            "healthy",
            "poll_succeeded" if observed else "check_succeeded",
            configured=True,
            succeeded=True,
            observed=observed,
        )

    def failure(
        self,
        provider: str,
        detail_code: str,
        *,
        rate_limited_until: datetime | None = None,
        immediate_unavailable: bool = False,
    ) -> ProviderHealth:
        with self._lock:
            previous = self._states.get(provider)
            count = (previous.consecutive_failures if previous else 0) + 1
            if detail_code in {
                "authentication_failed",
                "authorization_expired",
                "authorization_required",
                "authorization_exchange_failed",
                "not_authenticated",
                "reconnect_required",
                "stored_credentials_unavailable",
                "github_unauthorized",
                "github_forbidden",
                "permission_denied",
            }:
                status: ProviderStatusCode = "auth_failure"
            else:
                status = (
                    "unavailable" if immediate_unavailable or count >= 3 else "provider_failure"
                )
            return self.report(
                provider,
                status,
                detail_code,
                configured=True,
                failed=True,
                rate_limited_until=rate_limited_until,
            )

    def rate_limited(self, provider: str, detail_code: str, until: datetime) -> ProviderHealth:
        return self.report(
            provider,
            "rate_limited",
            detail_code,
            configured=True,
            failed=True,
            rate_limited_until=until,
        )

    def snapshot(self, settings: Settings | None = None) -> dict[str, dict[str, object]]:
        settings = settings or get_settings()
        configured = settings.provider_configuration()
        snapshots: dict[str, dict[str, object]] = {}
        with self._lock:
            current = dict(self._states)
        for provider in PROVIDER_IDS:
            state = current.get(provider)
            if state is None:
                is_configured = configured[provider]
                state = ProviderHealth(
                    provider=provider,
                    status="unknown" if is_configured else "disconnected",
                    configured=is_configured,
                    detail_code="implementation_pending"
                    if is_configured
                    else "configuration_missing",
                )
            snapshots[provider] = state.model_dump(mode="json")
        return snapshots


provider_health = ProviderHealthRegistry()
