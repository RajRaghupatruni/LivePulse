"""Clean current-weather service and freshness health for API consumers."""

from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal

from app.core.config import Settings
from app.providers.weather.client import WeatherConditions


class WeatherStateService:
    def __init__(self) -> None:
        self._current: WeatherConditions | None = None
        self._fetched_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_failure_code = "not_observed"
        self._lock = RLock()

    def update(self, current: WeatherConditions, *, fetched_at: datetime) -> None:
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        with self._lock:
            self._current = current
            self._fetched_at = fetched_at.astimezone(UTC)
            self._last_failure_at = None
            self._last_failure_code = "not_observed"

    def record_failure(self, detail_code: str, *, now: datetime | None = None) -> None:
        with self._lock:
            self._last_failure_at = (now or datetime.now(UTC)).astimezone(UTC)
            self._last_failure_code = detail_code

    def current(self) -> WeatherConditions | None:
        with self._lock:
            return self._current

    def health_snapshot(
        self, settings: Settings, *, now: datetime | None = None
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        configured = weather_configured(settings)
        with self._lock:
            fetched_at = self._fetched_at
            failure_at = self._last_failure_at
            failure_code = self._last_failure_code
        if not configured:
            status: Literal["healthy", "degraded", "disconnected", "unknown"] = "disconnected"
            freshness = "not_configured"
            detail_code = "configuration_missing"
        elif fetched_at is None:
            if failure_at:
                status = "degraded"
                freshness = "unknown"
                detail_code = failure_code
            else:
                status = "unknown"
                freshness = "unknown"
                detail_code = "not_observed"
        else:
            age = current_time - fetched_at
            if failure_at:
                status = "degraded"
                freshness = "fresh" if age <= timedelta(minutes=45) else "stale"
                detail_code = failure_code
            elif age <= timedelta(minutes=45):
                status, freshness, detail_code = "healthy", "fresh", "poll_succeeded"
            elif age <= timedelta(minutes=90):
                status, freshness, detail_code = "degraded", "stale", "poll_stale"
            else:
                status, freshness, detail_code = "degraded", "stale", "poll_overdue"
        return {
            "provider": "weather",
            "status": status,
            "configured": configured,
            "freshness": freshness,
            "detail_code": detail_code,
            "last_success_at": fetched_at.isoformat() if fetched_at else None,
            "last_failure_at": failure_at.isoformat() if failure_at else None,
        }

    def response(self, settings: Settings, *, now: datetime | None = None) -> dict[str, object]:
        with self._lock:
            current = self._current
            fetched_at = self._fetched_at
        return {
            "current": current.model_dump(mode="json") if current else None,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "health": self.health_snapshot(settings, now=now),
        }


def weather_configured(settings: Settings) -> bool:
    return (
        settings.weather_latitude is not None
        and settings.weather_longitude is not None
        and bool(settings.weather_timezone and settings.weather_timezone.strip())
    )


weather_state = WeatherStateService()
