from datetime import UTC, datetime, timedelta
from typing import Any, Literal

ComponentStatus = Literal["healthy", "degraded", "unavailable", "unknown"]

_components: dict[str, dict[str, Any]] = {}
_HEARTBEAT_TTL = {"outbox_publisher": timedelta(seconds=10), "projector": timedelta(seconds=10)}


def report_component(
    name: str,
    status: ComponentStatus,
    detail: str,
    *,
    succeeded: bool = False,
    metrics: dict[str, int | float | str | None] | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    previous = _components.get(name, {})
    component: dict[str, Any] = {
        "name": name,
        "status": status,
        "detail": detail,
        "checked_at": now,
        "last_success_at": now if succeeded else previous.get("last_success_at"),
    }
    if metrics:
        component["metrics"] = metrics
    _components[name] = component


def component_snapshot(name: str) -> dict[str, Any]:
    component = dict(
        _components.get(
            name,
            {
                "name": name,
                "status": "unknown",
                "detail": "not_observed",
                "checked_at": None,
                "last_success_at": None,
            },
        )
    )
    ttl = _HEARTBEAT_TTL.get(name)
    checked_at = component.get("checked_at")
    if ttl is not None and component["status"] == "healthy" and checked_at:
        age = datetime.now(UTC) - datetime.fromisoformat(checked_at)
        if age > ttl:
            component["status"] = "degraded"
            component["detail"] = "heartbeat_stale"
    return component


def overall_status(components: dict[str, dict[str, Any]]) -> ComponentStatus:
    statuses = {str(component["status"]) for component in components.values()}
    if "unavailable" in statuses:
        return "unavailable"
    if "degraded" in statuses:
        return "degraded"
    if "unknown" in statuses:
        return "unknown"
    return "healthy"
