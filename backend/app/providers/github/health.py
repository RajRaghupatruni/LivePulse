"""Capability-level GitHub health; values are normalized and contain no credentials."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.core.config import Settings
from app.providers.status import provider_health

HealthStatus = Literal[
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


class GithubHealthTracker:
    def __init__(self) -> None:
        self.last_webhook_received_at: datetime | None = None
        self.last_reconciliation_at: datetime | None = None
        self.last_reconciliation_success_at: datetime | None = None
        self.reconciliation_rate_limited_until: datetime | None = None
        self.reconciliation_status: HealthStatus = "unknown"
        self.reconciliation_detail = "not_observed"

    @staticmethod
    def webhook_configured(settings: Settings) -> bool:
        return bool(
            settings.github_owner
            and settings.github_owner.strip()
            and settings.github_webhook_secret
            and settings.github_webhook_secret.get_secret_value().strip()
        )

    @staticmethod
    def reconciliation_configured(settings: Settings) -> bool:
        return bool(
            settings.github_owner
            and settings.github_owner.strip()
            and settings.github_token
            and settings.github_token.get_secret_value().strip()
        )

    def initialize(self, settings: Settings) -> None:
        webhook = self.webhook_configured(settings)
        rest = self.reconciliation_configured(settings)
        configured = webhook or rest
        if not rest:
            self.reconciliation_status = "disconnected"
            self.reconciliation_detail = "token_missing"
        else:
            self.reconciliation_status = "connecting"
            self.reconciliation_detail = "awaiting_reconciliation"
        provider_health.report(
            "github",
            "connecting" if rest else ("degraded" if webhook else "disconnected"),
            "awaiting_reconciliation"
            if rest
            else ("reconciliation_disconnected" if webhook else "configuration_missing"),
            configured=configured,
        )

    def note_webhook(self, settings: Settings, *, now: datetime | None = None) -> None:
        self.last_webhook_received_at = (now or datetime.now(UTC)).astimezone(UTC)
        if self.reconciliation_configured(settings):
            return
        provider_health.report(
            "github",
            "degraded",
            "reconciliation_disconnected",
            configured=True,
            succeeded=True,
            observed=True,
        )

    def note_reconciliation_attempt(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self.last_reconciliation_at = current
        if self.reconciliation_status in {"unknown", "connecting"}:
            self.reconciliation_status = "connecting"
            self.reconciliation_detail = "reconciliation_in_progress"

    def note_reconciliation_success(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self.last_reconciliation_at = current
        self.last_reconciliation_success_at = current
        self.reconciliation_status = "healthy"
        self.reconciliation_detail = "reconciliation_succeeded"
        self.reconciliation_rate_limited_until = None

    def note_reconciliation_failure(
        self,
        detail_code: str,
        *,
        now: datetime | None = None,
        rate_limited_until: datetime | None = None,
    ) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self.last_reconciliation_at = current
        if rate_limited_until is not None or "rate_limit" in detail_code:
            self.reconciliation_status = "rate_limited"
        elif detail_code in {"github_unauthorized", "github_forbidden"}:
            self.reconciliation_status = "auth_failure"
        else:
            self.reconciliation_status = "provider_failure"
        self.reconciliation_detail = detail_code
        self.reconciliation_rate_limited_until = rate_limited_until

    def snapshot(self, settings: Settings, *, now: datetime | None = None) -> dict[str, object]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        webhook_configured = self.webhook_configured(settings)
        rest_configured = self.reconciliation_configured(settings)
        rest_status = self.reconciliation_status if rest_configured else "disconnected"
        rest_detail = self.reconciliation_detail if rest_configured else "token_missing"
        if rest_configured and self.last_reconciliation_at and (
            current - self.last_reconciliation_at > timedelta(minutes=20)
        ):
            rest_status = "stale"
            rest_detail = "reconciliation_stale"
        if webhook_configured:
            webhook_status: HealthStatus = (
                "healthy" if self.last_webhook_received_at else "connecting"
            )
            webhook_detail = "webhook_delivery_verified" if self.last_webhook_received_at else (
                "awaiting_delivery"
            )
        else:
            webhook_status = "disconnected"
            webhook_detail = "configuration_missing"
        return {
            "provider": "github",
            "configured": webhook_configured or rest_configured,
            "status": _combined_status(webhook_status, rest_status),
            "webhook": {
                "configured": webhook_configured,
                "listening": True,
                "status": webhook_status,
                "detail_code": webhook_detail,
                "last_received_at": _iso(self.last_webhook_received_at),
            },
            "reconciliation": {
                "configured": rest_configured,
                "status": rest_status,
                "detail_code": rest_detail,
                "last_attempt_at": _iso(self.last_reconciliation_at),
                "last_success_at": _iso(self.last_reconciliation_success_at),
                "rate_limited_until": _iso(self.reconciliation_rate_limited_until),
            },
        }


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _combined_status(webhook: HealthStatus, rest: HealthStatus) -> HealthStatus:
    for status in ("auth_failure", "rate_limited", "provider_failure", "unavailable"):
        if rest == status:
            return status  # type: ignore[return-value]
    if rest == "stale":
        return "stale"
    if rest == "healthy":
        return "healthy"
    if webhook != "disconnected" and rest == "disconnected":
        return "degraded"
    if "degraded" in {webhook, rest}:
        return "degraded"
    if "connecting" in {webhook, rest} or "resyncing" in {webhook, rest}:
        return "connecting"
    if webhook == rest == "disconnected":
        return "disconnected"
    return "unknown"


github_health = GithubHealthTracker()
