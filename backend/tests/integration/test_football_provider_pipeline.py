import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select
from uuid6 import uuid7

from app.providers.base import PollContext
from app.providers.football.api import FootballApiClient
from app.providers.football.models import FootballFixtureObservation
from app.providers.football.source import FootballPollSource
from app.providers.football.store import FootballCheckpointStore
from app.providers.observations import Observation
from app.storage.database import SessionFactory
from app.storage.models import CanonicalEventRow, OutboxMessageRow, ProviderCheckpointRow

pytestmark = pytest.mark.skipif(
    os.getenv("LIVEPULSE_INTEGRATION") != "1",
    reason="requires local PostgreSQL; provider HTTP remains fixture-mocked",
)
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "api_football"
OBSERVED_AT = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, tuple[dict[str, Any], datetime]] = {}

    async def get_json(self, key: str):
        return self.values.get(key)

    async def put_json(self, key: str, value: dict[str, Any], *, observed_at=None) -> None:
        self.values[key] = (value, observed_at or OBSERVED_AT)

    async def list_json(self, prefix: str):
        return [(key, value) for key, (value, _) in self.values.items() if key.startswith(prefix)]


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def reidentify(body: dict[str, Any], fixture_id: int) -> dict[str, Any]:
    copied = json.loads(json.dumps(body))
    for fixture in copied.get("response", []):
        fixture["fixture"]["id"] = fixture_id
    return copied


@pytest.mark.asyncio(loop_scope="module")
async def test_api_fixture_observation_uses_m1_event_and_outbox_persistence() -> None:
    fixture_id = int(uuid7().int % 700_000_000) + 100_000_000
    upcoming_id = fixture_id + 1

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/leagues":
            body = load_json("leagues_current.json")
        elif "from" in request.url.params:
            if request.url.params["league"] == "39":
                body = reidentify(load_json("fixtures_today.json"), fixture_id)
            else:
                body = {"errors": [], "results": 0, "response": []}
        elif "live" in request.url.params:
            body = reidentify(load_json("fixtures_live.json"), fixture_id)
        elif "ids" in request.url.params:
            body = reidentify(load_json("fixtures_by_ids.json"), fixture_id)
        else:
            raise AssertionError(f"unexpected mocked endpoint {request.url.path}")
        if request.url.params.get("league") == "39" and "from" in request.url.params:
            body["response"][1]["fixture"]["id"] = upcoming_id
        return httpx.Response(200, json=body)

    subject_ids = [f"api-football:fixture:{fixture_id}", f"api-football:fixture:{upcoming_id}"]
    checkpoint_keys = [f"fixture:{fixture_id}", f"fixture:{upcoming_id}"]
    await _cleanup(subject_ids, checkpoint_keys)
    store = MemoryStore()
    api = FootballApiClient("mocked-test-key", transport=httpx.MockTransport(handler))
    source = FootballPollSource(api, store=store, clock=lambda: OBSERVED_AT)  # type: ignore[arg-type]
    database_store = FootballCheckpointStore()
    try:
        observations = await source.observe(
            context=PollContext(correlation_id=uuid7(), scheduled_at=OBSERVED_AT)
        )
        assert observations
        assert any(
            item.content.fixture_id == fixture_id and item.content.events for item in observations
        )

        # This is the production ingestion method: it calls persist_event_and_outbox
        # and advances fixture checkpoints within the same database transaction.
        ingest_context = PollContext(correlation_id=uuid7(), scheduled_at=OBSERVED_AT)
        persisted = await database_store.ingest(list(observations), ingest_context)
        assert persisted >= 7

        live = next(item.content for item in observations if item.content.fixture_id == fixture_id)
        fulltime_observation = Observation[FootballFixtureObservation](
            provider_id="football",
            external_entity_id=live.external_entity_id,
            observed_at=OBSERVED_AT + timedelta(minutes=12),
            content=live.model_copy(
                update={"status_code": "FT", "status_label": "Match Finished", "minute": 90}
            ),
            correlation_id=ingest_context.correlation_id,
        )
        await database_store.ingest([fulltime_observation], ingest_context)
        verified_observation = fulltime_observation.model_copy(
            update={
                "observed_at": OBSERVED_AT + timedelta(minutes=14),
                "content": fulltime_observation.content.model_copy(
                    update={"final_verification": True}
                ),
            }
        )
        await database_store.ingest([verified_observation], ingest_context)
        async with SessionFactory() as session:
            events = list(
                await session.scalars(
                    select(CanonicalEventRow).where(CanonicalEventRow.subject_id == subject_ids[0])
                )
            )
            outbox = list(
                await session.scalars(
                    select(OutboxMessageRow).where(OutboxMessageRow.partition_key == subject_ids[0])
                )
            )
            checkpoint = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == checkpoint_keys[0],
                )
            )
            pending_final = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == "pending-final",
                )
            )
        assert {item.event_type for item in events} >= {
            "football.match.scheduled",
            "football.match.kickoff",
            "football.match.goal",
            "football.match.yellow_card",
            "football.match.substitution",
            "football.match.halftime",
            "football.match.second_half",
            "football.match.fulltime",
        }
        assert len(outbox) == len(events)
        assert checkpoint is not None
        assert json.loads(checkpoint.checkpoint_value)["final_verification_pending"] is False
        assert pending_final is not None
        assert fixture_id not in json.loads(pending_final.checkpoint_value)["fixture_ids"]
        assert "api-football:fixture" not in json.dumps(events[0].payload)
    finally:
        await source.close()
        await _cleanup(subject_ids, checkpoint_keys)


async def _cleanup(subject_ids: list[str], checkpoint_keys: list[str]) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(
                delete(CanonicalEventRow).where(CanonicalEventRow.subject_id.in_(subject_ids))
            )
            await session.execute(
                delete(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key.in_(checkpoint_keys),
                )
            )
