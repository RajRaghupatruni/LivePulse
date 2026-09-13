import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from uuid6 import uuid7

from app.providers.base import PollContext
from app.providers.football.api import FootballApiClient
from app.providers.football.ingestion import diff_fixture
from app.providers.football.models import FootballFixtureObservation, NormalizedMatchEvent
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

    async def ingest(self, observations, _context) -> int:
        return 0


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def reidentify(body: dict[str, Any], fixture_id: int) -> dict[str, Any]:
    copied = json.loads(json.dumps(body))
    for fixture in copied.get("response", []):
        fixture["fixture"]["id"] = fixture_id
    return copied


@pytest.mark.asyncio(loop_scope="module")
async def test_api_fixture_observation_uses_m1_event_and_outbox_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import app.providers.football.store as football_store_module

    fixture_id = int(uuid7().int % 700_000_000) + 100_000_000
    upcoming_id = fixture_id + 1
    baseline_key = f"fixture-baseline-test:{uuid4().hex}"
    monkeypatch.setattr(football_store_module, "BASELINE_CHECKPOINT_KEY", baseline_key)

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
    checkpoint_keys = [f"fixture:{fixture_id}", f"fixture:{upcoming_id}", baseline_key]
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


@pytest.mark.asyncio(loop_scope="module")
async def test_initial_fixture_baseline_is_quiet_and_later_changes_are_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import app.providers.football.store as football_store_module

    run_id = uuid4().hex
    baseline_key = f"fixture-baseline-test:{run_id}"
    monkeypatch.setattr(football_store_module, "BASELINE_CHECKPOINT_KEY", baseline_key)

    async def no_legacy_checkpoints(_session) -> bool:
        # The opt-in suite shares PERSONAL_LOCAL, which already has production
        # fixture checkpoints. Model a fresh scope without deleting that data.
        return False

    monkeypatch.setattr(football_store_module, "_has_fixture_checkpoints", no_legacy_checkpoints)
    store = FootballCheckpointStore()
    first_id = int(uuid7().int % 700_000_000) + 100_000_000
    fixture_ids = [first_id + offset for offset in range(128)]
    subjects = [f"api-football:fixture:{fixture_id}" for fixture_id in fixture_ids]
    checkpoint_keys = [f"fixture:{fixture_id}" for fixture_id in fixture_ids]
    checkpoint_keys.append(baseline_key)

    def make_observation(
        fixture_id: int,
        *,
        status: str = "NS",
        minute: int = 0,
        score: int = 0,
        events: tuple[NormalizedMatchEvent, ...] = (),
        observed_at: datetime = OBSERVED_AT,
    ) -> Observation[FootballFixtureObservation]:
        content = FootballFixtureObservation(
            fixture_id=fixture_id,
            league_id=39,
            competition="Premier League",
            home_team=f"Home {fixture_id}",
            away_team=f"Away {fixture_id}",
            kickoff_at=OBSERVED_AT + timedelta(days=2),
            status_code=status,
            status_label=status,
            minute=minute,
            home_score=score,
            away_score=0,
            events=events,
        )
        return Observation[FootballFixtureObservation](
            provider_id="football",
            external_entity_id=content.external_entity_id,
            observed_at=observed_at,
            content=content,
            correlation_id=uuid7(),
        )

    initial = [make_observation(fixture_id) for fixture_id in fixture_ids]
    context = PollContext(correlation_id=uuid7(), scheduled_at=OBSERVED_AT)
    try:
        # A large first result establishes durable fixture state without
        # treating every existing schedule as a new user-visible event.
        assert await store.ingest(initial, context) == 0
        async with SessionFactory() as session:
            stored_fixtures = list(
                await session.scalars(
                    select(ProviderCheckpointRow).where(
                        ProviderCheckpointRow.provider == "football",
                        ProviderCheckpointRow.checkpoint_key.in_(checkpoint_keys),
                    )
                )
            )
            baseline = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == baseline_key,
                )
            )
            event_count = await session.scalar(
                select(func.count())
                .select_from(CanonicalEventRow)
                .where(CanonicalEventRow.subject_id.in_(subjects))
            )
        assert len(stored_fixtures) == len(fixture_ids) + 1
        assert baseline is not None
        assert json.loads(baseline.checkpoint_value)["initial_sync"] is True
        assert event_count == 0

        # A new store represents a backend restart: repeated baseline data is
        # still a no-op because both the fixture state and marker are durable.
        restarted_store = FootballCheckpointStore()
        assert (
            await restarted_store.ingest(
                initial,
                PollContext(
                    correlation_id=uuid7(), scheduled_at=OBSERVED_AT + timedelta(minutes=1)
                ),
            )
            == 0
        )

        new_fixture_id = fixture_ids[-1] + 10
        new_fixture = make_observation(new_fixture_id)
        assert (
            await restarted_store.ingest(
                [new_fixture],
                PollContext(
                    correlation_id=uuid7(), scheduled_at=OBSERVED_AT + timedelta(minutes=2)
                ),
            )
            == 1
        )

        goal = NormalizedMatchEvent(
            identity=f"goal:{run_id}", kind="Goal", minute=12, side="home", player="Forward"
        )
        changed = make_observation(
            new_fixture_id,
            status="1H",
            minute=12,
            score=1,
            events=(goal,),
            observed_at=OBSERVED_AT + timedelta(minutes=3),
        )
        assert (
            await restarted_store.ingest(
                [changed], PollContext(correlation_id=uuid7(), scheduled_at=changed.observed_at)
            )
            == 2
        )
        assert (
            await restarted_store.ingest(
                [changed], PollContext(correlation_id=uuid7(), scheduled_at=changed.observed_at)
            )
            == 0
        )

        async with SessionFactory() as session:
            events = list(
                await session.scalars(
                    select(CanonicalEventRow).where(
                        CanonicalEventRow.subject_id == new_fixture.content.external_entity_id
                    )
                )
            )
            outbox = list(
                await session.scalars(
                    select(OutboxMessageRow).where(
                        OutboxMessageRow.partition_key == new_fixture.content.external_entity_id
                    )
                )
            )
        assert sorted(item.event_type for item in events) == [
            "football.match.goal",
            "football.match.kickoff",
            "football.match.scheduled",
        ]
        assert len(outbox) == len(events) == 3
    finally:
        await _cleanup(
            subjects + [f"api-football:fixture:{fixture_ids[-1] + 10}"],
            checkpoint_keys + [f"fixture:{fixture_ids[-1] + 10}"],
        )


@pytest.mark.asyncio(loop_scope="module")
async def test_existing_fixture_checkpoints_recognize_legacy_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import app.providers.football.store as football_store_module

    baseline_key = f"fixture-baseline-test:{uuid4().hex}"
    monkeypatch.setattr(football_store_module, "BASELINE_CHECKPOINT_KEY", baseline_key)
    existing_id = int(uuid7().int % 700_000_000) + 100_000_000
    new_id = existing_id + 1
    subjects = [f"api-football:fixture:{existing_id}", f"api-football:fixture:{new_id}"]
    checkpoint_keys = [f"fixture:{existing_id}", f"fixture:{new_id}", baseline_key]

    def make_observation(fixture_id: int) -> Observation[FootballFixtureObservation]:
        content = FootballFixtureObservation(
            fixture_id=fixture_id,
            league_id=39,
            competition="Premier League",
            home_team=f"Home {fixture_id}",
            away_team=f"Away {fixture_id}",
            kickoff_at=OBSERVED_AT + timedelta(days=2),
            status_code="NS",
            status_label="Not Started",
            home_score=0,
            away_score=0,
        )
        return Observation[FootballFixtureObservation](
            provider_id="football",
            external_entity_id=content.external_entity_id,
            observed_at=OBSERVED_AT,
            content=content,
            correlation_id=uuid7(),
        )

    existing = make_observation(existing_id)
    new = make_observation(new_id)
    _, checkpoint_state = diff_fixture(None, existing, correlation_id=uuid7())
    encoded_state = json.dumps(checkpoint_state, separators=(",", ":"), sort_keys=True)
    try:
        async with SessionFactory() as session:
            async with session.begin():
                session.add(
                    ProviderCheckpointRow(
                        provider="football",
                        checkpoint_key=f"fixture:{existing_id}",
                        checkpoint_value=encoded_state,
                        observed_at=OBSERVED_AT,
                    )
                )

        # The legacy checkpoint belongs to an earlier fixture/window and is
        # intentionally absent from this provider result.
        persisted = await FootballCheckpointStore().ingest(
            [new],
            PollContext(correlation_id=uuid7(), scheduled_at=OBSERVED_AT),
        )
        async with SessionFactory() as session:
            new_events = list(
                await session.scalars(
                    select(CanonicalEventRow).where(
                        CanonicalEventRow.subject_id == new.content.external_entity_id
                    )
                )
            )
            marker = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == baseline_key,
                )
            )
        assert persisted == 1
        assert [item.event_type for item in new_events] == ["football.match.scheduled"]
        assert marker is not None
        assert json.loads(marker.checkpoint_value)["initial_sync"] is False
    finally:
        await _cleanup(subjects, checkpoint_keys)


@pytest.mark.asyncio(loop_scope="module")
async def test_empty_sync_becomes_baseline_before_a_later_fixture_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import app.providers.football.store as football_store_module

    baseline_key = f"fixture-baseline-test:{uuid4().hex}"
    monkeypatch.setattr(football_store_module, "BASELINE_CHECKPOINT_KEY", baseline_key)
    fixture_id = int(uuid7().int % 700_000_000) + 100_000_000
    subject = f"api-football:fixture:{fixture_id}"
    checkpoint_keys = [f"fixture:{fixture_id}", baseline_key]
    content = FootballFixtureObservation(
        fixture_id=fixture_id,
        league_id=39,
        competition="Premier League",
        home_team="Home FC",
        away_team="Away FC",
        kickoff_at=OBSERVED_AT + timedelta(days=2),
        status_code="NS",
        status_label="Not Started",
        home_score=0,
        away_score=0,
    )
    observation = Observation[FootballFixtureObservation](
        provider_id="football",
        external_entity_id=content.external_entity_id,
        observed_at=OBSERVED_AT,
        content=content,
        correlation_id=uuid7(),
    )
    store = FootballCheckpointStore()
    try:
        assert (
            await store.ingest([], PollContext(correlation_id=uuid7(), scheduled_at=OBSERVED_AT))
            == 0
        )
        async with SessionFactory() as session:
            marker = await session.scalar(
                select(ProviderCheckpointRow).where(
                    ProviderCheckpointRow.provider == "football",
                    ProviderCheckpointRow.checkpoint_key == baseline_key,
                )
            )
        assert marker is not None
        marker_state = json.loads(marker.checkpoint_value)
        assert marker_state["established_at"] == OBSERVED_AT.isoformat()
        assert marker_state["fixture_count"] == 0
        assert isinstance(marker_state["initial_sync"], bool)

        assert (
            await store.ingest(
                [observation],
                PollContext(
                    correlation_id=uuid7(), scheduled_at=OBSERVED_AT + timedelta(minutes=1)
                ),
            )
            == 1
        )
        async with SessionFactory() as session:
            event = await session.scalar(
                select(CanonicalEventRow).where(CanonicalEventRow.subject_id == subject)
            )
        assert event is not None and event.event_type == "football.match.scheduled"
    finally:
        await _cleanup([subject], checkpoint_keys)


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
