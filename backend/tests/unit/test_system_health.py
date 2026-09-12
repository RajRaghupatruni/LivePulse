from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.api import routes
from app.core.health import _components, component_snapshot, overall_status, report_component


def test_health_aggregation_never_promotes_unknown_or_failed_dependencies() -> None:
    assert overall_status({"postgres": {"status": "unknown"}}) == "unknown"
    assert overall_status(
        {"postgres": {"status": "healthy"}, "projector": {"status": "degraded"}}
    ) == "degraded"
    assert overall_status(
        {"postgres": {"status": "unavailable"}, "redpanda": {"status": "healthy"}}
    ) == "unavailable"


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
