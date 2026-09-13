import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from uuid6 import uuid7

from app.domain.events import FootballEventType
from app.providers.base import PollContext
from app.providers.football.api import (
    DailyRequestBudget,
    FootballApiClient,
    FootballAuthenticationError,
    FootballRateLimitError,
)
from app.providers.football.cadence import adaptive_cadence
from app.providers.football.ingestion import diff_fixture
from app.providers.football.leagues import (
    LOCKED_COMPETITIONS,
    canonical_competition,
    resolve_league_catalog,
)
from app.providers.football.models import (
    FixtureEnvelope,
    FootballFixtureObservation,
    NormalizedMatchEvent,
)
from app.providers.football.normalize import normalize_fixture
from app.providers.football.source import FootballPollSource
from app.providers.football.store import FootballCheckpointStore
from app.providers.observations import Observation
from app.providers.status import ProviderHealthRegistry

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "api_football"
NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


def fixture_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def make_match(
    *,
    status: str = "NS",
    minute: int = 0,
    home_score: int | None = 0,
    away_score: int | None = 0,
    events: tuple[NormalizedMatchEvent, ...] = (),
    kickoff: datetime = datetime(2026, 9, 12, 20, 0, tzinfo=UTC),
    fixture_id: int = 990001,
    final_verification: bool = False,
) -> FootballFixtureObservation:
    return FootballFixtureObservation(
        fixture_id=fixture_id,
        league_id=39,
        competition="Premier League",
        home_team="Northbridge FC",
        away_team="Riverside United",
        home_team_id=101,
        away_team_id=202,
        kickoff_at=kickoff,
        status_code=status,
        status_label=status,
        minute=minute,
        home_score=home_score,
        away_score=away_score,
        events=events,
        final_verification=final_verification,
    )


def observation(
    content: FootballFixtureObservation, *, observed_at: datetime = NOW
) -> Observation[FootballFixtureObservation]:
    return Observation[FootballFixtureObservation](
        provider_id="football",
        external_entity_id=content.external_entity_id,
        observed_at=observed_at,
        content=content,
        correlation_id=uuid7(),
    )


def event(
    identity: str,
    kind: str,
    minute: int,
    *,
    side: str | None = None,
    player: str | None = None,
    assist: str | None = None,
    detail: str | None = None,
) -> NormalizedMatchEvent:
    return NormalizedMatchEvent(
        identity=identity,
        kind=kind,
        minute=minute,
        side=side,
        player=player,
        assist=assist,
        detail=detail,
    )


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, tuple[dict[str, Any], datetime]] = {}

    async def get_json(self, key: str):
        return self.values.get(key)

    async def put_json(self, key: str, value: dict[str, Any], *, observed_at=None) -> None:
        self.values[key] = (value, observed_at or NOW)

    async def list_json(self, prefix: str):
        return [(key, value) for key, (value, _) in self.values.items() if key.startswith(prefix)]


def test_api_football_fixture_dtos_validate_current_response_shape() -> None:
    response = FixtureEnvelope.model_validate(fixture_json("fixtures_by_ids.json"))
    fixture = response.response[0]
    assert fixture.fixture.id == 190001
    assert fixture.fixture.status.short == "2H"
    assert fixture.goals.home == 2
    assert len(fixture.events or []) == 5
    assert fixture.events[2].type == "subst"


def test_locked_leagues_resolve_from_metadata_and_aliases() -> None:
    from app.providers.football.models import LeagueEnvelope

    metadata = LeagueEnvelope.model_validate(fixture_json("leagues_current.json"))
    catalog = resolve_league_catalog(metadata.response)
    assert len(catalog) == len(LOCKED_COMPETITIONS) == 11
    assert catalog["Premier League"] == 39
    assert catalog["Carabao Cup"] == 48
    assert canonical_competition("EPL", "England") == "Premier League"
    assert canonical_competition("Champions League", "World") == "UEFA Champions League"
    assert canonical_competition("League Cup", "England") == "Carabao Cup"
    assert canonical_competition("Championship", "Scotland") is None

    raw = metadata.response[0]
    record = fixture_json("fixtures_by_ids.json")["response"][0]
    api_fixture = FixtureEnvelope.model_validate({"response": [record]}).response[0]
    normalized = normalize_fixture(api_fixture, canonical_competitions={39: "Premier League"})
    rejected = normalize_fixture(api_fixture, canonical_competitions={999: "Premier League"})
    assert normalized is not None and normalized.competition == "Premier League"
    assert rejected is None
    assert raw.league.name == "Premier League"


@pytest.mark.asyncio
async def test_http_client_sends_secret_header_and_batches_fixture_ids() -> None:
    requested: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"errors": [], "results": 0, "response": []})

    client = FootballApiClient("fake-private-key", transport=httpx.MockTransport(handler))
    try:
        fixtures = await client.fixtures_by_ids(list(range(1, 22)))
    finally:
        await client.close()
    assert fixtures == []
    assert len(requested) == 2
    assert requested[0].headers["x-apisports-key"] == "fake-private-key"
    assert len(requested[0].url.params["ids"].split("-")) == 20
    assert requested[1].url.params["ids"] == "21"


@pytest.mark.asyncio
async def test_fixture_date_response_pagination_is_followed() -> None:
    requests: list[httpx.Request] = []
    request_started_at: list[float] = []
    day_fixtures = fixture_json("fixtures_today.json")["response"]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        request_started_at.append(asyncio.get_running_loop().time())
        page = request.url.params.get("page", "1")
        record = day_fixtures[int(page) - 1]
        return httpx.Response(
            200,
            json={
                "errors": [],
                "results": 1,
                "paging": {"current": int(page), "total": 2},
                "response": [record],
            },
        )

    client = FootballApiClient(
        "fixture-pagination-key",
        transport=httpx.MockTransport(handler),
        min_request_interval=0.01,
    )
    try:
        records = await client.fixtures_by_date(date(2026, 9, 12))
    finally:
        await client.close()
    assert [item.fixture.id for item in records] == [190001, 190002]
    assert [request.url.params.get("page") for request in requests] == [None, "2"]
    assert request_started_at[1] - request_started_at[0] >= 0.007


@pytest.mark.asyncio
async def test_api_client_translates_429_and_honors_retry_after() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={
                "Retry-After": "30",
                "x-ratelimit-requests-limit": "100",
                "x-ratelimit-requests-remaining": "80",
                "X-RateLimit-Remaining": "8",
            },
            json={"errors": ["Too many requests"], "response": []},
        )

    budget = DailyRequestBudget()
    client = FootballApiClient(
        SecretStr("secret-do-not-log"), budget=budget, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(FootballRateLimitError) as raised:
            await client.leagues_current()
    finally:
        await client.close()
    assert 29 <= (raised.value.retry_after - datetime.now(UTC)).total_seconds() <= 30
    assert raised.value.detail_code == "rate_limited"
    assert budget.requests_used == 1
    assert budget.requests_remaining_header == 80
    assert budget.requests_per_minute_remaining == 8
    assert "secret-do-not-log" not in str(raised.value)


@pytest.mark.asyncio
async def test_league_smoke_search_is_scoped_to_current_named_competition() -> None:
    requested: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=fixture_json("leagues_current.json"))

    client = FootballApiClient("fixture-smoke-key", transport=httpx.MockTransport(handler))
    try:
        records = await client.leagues_search("Premier League")
    finally:
        await client.close()
    assert records
    assert len(requested) == 1
    assert requested[0].url.path == "/leagues"
    assert dict(requested[0].url.params) == {
        "search": "Premier League",
        "current": "true",
    }


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_api_auth_failures_are_permanent_and_secret_free(status: int) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    client = FootballApiClient("fake-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(FootballAuthenticationError) as raised:
            await client.leagues_current()
    finally:
        await client.close()
    assert raised.value.permanent is True
    assert "fake-secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_daily_quota_tracks_headers_local_fallback_and_utc_reset() -> None:
    writes: list[dict[str, Any]] = []

    async def persist(snapshot: dict[str, Any]) -> None:
        writes.append(snapshot)

    budget = DailyRequestBudget(persist=persist)
    start = datetime(2026, 9, 12, 23, 59, tzinfo=UTC)
    assert budget.can_request(now=start)
    await budget.reserve(now=start)
    await budget.update_headers(
        {
            "x-ratelimit-requests-limit": "100",
            "x-ratelimit-requests-remaining": "72",
            "X-RateLimit-Remaining": "9",
        },
        now=start,
    )
    snapshot = budget.snapshot(now=start)
    assert snapshot["requests_used"] == 1
    assert snapshot["requests_remaining"] == 72
    assert snapshot["local_remaining"] == 99
    assert snapshot["requests_per_minute_remaining"] == 9
    assert snapshot["next_reset_at"] == "2026-09-13T00:00:00+00:00"
    budget.requests_used = 95
    budget.requests_remaining_header = None
    assert not budget.can_request(now=start)
    with pytest.raises(FootballRateLimitError) as exhausted:
        await budget.reserve(now=start)
    assert exhausted.value.retry_after == datetime(2026, 9, 13, 0, tzinfo=UTC)
    budget.restore(snapshot, now=start + timedelta(minutes=2))
    assert budget.requests_used == 0
    assert budget.requests_remaining_header is None
    assert budget.can_request(now=start + timedelta(minutes=2))
    await budget.reserve(now=start + timedelta(minutes=2))
    assert budget.requests_used == 1
    assert len(writes) == 3


def test_adaptive_cadence_covers_idle_upcoming_live_halftime_and_quota() -> None:
    idle = make_match(status="FT", kickoff=NOW - timedelta(hours=2))
    assert adaptive_cadence([], now=NOW, quota_remaining=95) == timedelta(hours=12)
    assert adaptive_cadence(
        [make_match(kickoff=NOW + timedelta(hours=8))], now=NOW, quota_remaining=95
    ) == timedelta(hours=3)
    assert adaptive_cadence(
        [make_match(kickoff=NOW + timedelta(minutes=20))], now=NOW, quota_remaining=95
    ) == timedelta(minutes=5)
    assert adaptive_cadence(
        [make_match(kickoff=NOW + timedelta(minutes=4))], now=NOW, quota_remaining=95
    ) == timedelta(seconds=150)
    assert adaptive_cadence([make_match(status="1H")], now=NOW, quota_remaining=95) == timedelta(
        seconds=150
    )
    assert adaptive_cadence([make_match(status="HT")], now=NOW, quota_remaining=95) == timedelta(
        minutes=5
    )
    assert adaptive_cadence(
        [idle.model_copy(update={"final_verification": True})], now=NOW, quota_remaining=95
    ) == timedelta(minutes=2)
    assert adaptive_cadence([make_match(status="1H")], now=NOW, quota_remaining=20) == timedelta(
        minutes=5
    )
    assert adaptive_cadence([make_match(status="1H")], now=NOW, quota_remaining=10) == timedelta(
        minutes=10
    )
    assert adaptive_cadence([make_match(status="1H")], now=NOW, quota_remaining=40) == timedelta(
        minutes=3
    )
    assert adaptive_cadence(
        [make_match(status="1H")], now=NOW, quota_remaining=95, request_cost=2
    ) == timedelta(minutes=5)


def test_cadence_decision_explains_live_quota_degradation_and_idle_slowdown() -> None:
    from app.providers.football.cadence import adaptive_cadence_decision

    healthy = adaptive_cadence_decision([make_match(status="2H")], now=NOW, quota_remaining=80)
    low = adaptive_cadence_decision([make_match(status="2H")], now=NOW, quota_remaining=14)
    idle = adaptive_cadence_decision([], now=NOW, quota_remaining=80)

    assert healthy.interval == timedelta(seconds=150)
    assert healthy.reason == "active_live_match"
    assert low.interval == timedelta(minutes=10)
    assert low.reason == "daily_quota_degraded_10m"
    assert idle.interval == timedelta(hours=12)
    assert idle.reason == "no_live_or_upcoming_match"


def test_upcoming_fixture_service_covers_a_seven_day_horizon() -> None:
    from app.providers.football.service import FootballFixtureService

    service = FootballFixtureService()
    fifth_day = make_match(kickoff=NOW + timedelta(days=5))
    service.replace([fifth_day], observed_at=NOW)

    assert [item.fixture_id for item in service.upcoming(now=NOW)] == [fifth_day.fixture_id]


def test_missing_key_keeps_provider_disconnected() -> None:
    assert FootballPollSource.from_configuration(None) is None
    assert FootballPollSource.from_configuration("  ") is None


def test_duplicate_snapshot_and_repeated_event_array_suppress_duplicate_events() -> None:
    goal = event("provider-goal-1", "Goal", 25, side="home", player="A. Vale")
    content = make_match(status="1H", minute=25, home_score=1, events=(goal, goal))
    run_id = uuid7()
    created, checkpoint = diff_fixture(None, observation(content), correlation_id=run_id)
    assert sum(item.event_type == FootballEventType.GOAL.value for item in created) == 1
    repeated, same_checkpoint = diff_fixture(
        checkpoint,
        observation(content, observed_at=NOW + timedelta(minutes=2)),
        correlation_id=run_id,
    )
    assert repeated == []
    assert same_checkpoint["version"] == checkpoint["version"]


def test_goal_card_and_substitution_map_to_canonical_families() -> None:
    content = make_match(
        status="2H",
        minute=67,
        home_score=1,
        away_score=1,
        events=(
            event("goal-home", "Goal", 12, side="home", player="A. Vale"),
            event("yellow-away", "Card", 31, side="away", player="J. Reed", detail="Yellow Card"),
            event(
                "sub-home",
                "subst",
                52,
                side="home",
                player="R. Hale",
                assist="T. Brooks",
                detail="Substitution 1",
            ),
            event("goal-away", "Goal", 67, side="away", player="L. Noor"),
        ),
    )
    created, _ = diff_fixture(None, observation(content), correlation_id=uuid7())
    types = [item.event_type for item in created]
    assert types.count(FootballEventType.GOAL.value) == 2
    assert FootballEventType.YELLOW_CARD.value in types
    assert FootballEventType.SUBSTITUTION.value in types
    assert types.index(FootballEventType.HALFTIME.value) < types.index(
        FootballEventType.SUBSTITUTION.value
    )
    assert types.index(FootballEventType.SECOND_HALF.value) < types.index(
        FootballEventType.SUBSTITUTION.value
    )
    substitution = next(item for item in created if item.event_type.endswith("substitution"))
    assert substitution.payload["player"] == "R. Hale"
    assert substitution.payload["substitute"] == "T. Brooks"


def test_halftime_second_half_fulltime_and_event_order() -> None:
    content = make_match(
        status="FT",
        minute=90,
        home_score=1,
        away_score=1,
        events=(
            event("goal-first-half", "Goal", 12, side="home"),
            event("goal-second-half", "Goal", 52, side="away"),
        ),
    )
    created, checkpoint = diff_fixture(None, observation(content), correlation_id=uuid7())
    types = [item.event_type for item in created]
    assert types == [
        FootballEventType.SCHEDULED.value,
        FootballEventType.KICKOFF.value,
        FootballEventType.GOAL.value,
        FootballEventType.HALFTIME.value,
        FootballEventType.SECOND_HALF.value,
        FootballEventType.GOAL.value,
        FootballEventType.FULLTIME.value,
    ]
    assert checkpoint["final_verification_pending"] is True
    verified, confirmed = diff_fixture(
        checkpoint,
        observation(content.model_copy(update={"final_verification": True})),
        correlation_id=uuid7(),
    )
    assert verified == []
    assert confirmed["final_verification_pending"] is False


def test_var_score_correction_and_repeated_corrected_score() -> None:
    goal = event("goal-var", "Goal", 28, side="home", player="A. Vale", detail="Normal Goal")
    initial = make_match(status="1H", minute=28, home_score=1, away_score=0, events=(goal,))
    first, checkpoint = diff_fixture(None, observation(initial), correlation_id=uuid7())
    assert any(item.event_type == FootballEventType.GOAL.value for item in first)

    corrected = initial.model_copy(
        update={
            "home_score": 0,
            "events": (goal.model_copy(update={"detail": "Goal Disallowed"}),),
        }
    )
    correction, corrected_checkpoint = diff_fixture(
        checkpoint,
        observation(corrected, observed_at=NOW + timedelta(minutes=1)),
        correlation_id=uuid7(),
    )
    assert [item.event_type for item in correction] == [FootballEventType.SCORE_CORRECTED.value]
    assert correction[0].payload["home_score"] == 0
    repeated, _ = diff_fixture(
        corrected_checkpoint,
        observation(corrected, observed_at=NOW + timedelta(minutes=2)),
        correlation_id=uuid7(),
    )
    assert repeated == []


def test_score_increase_without_events_is_goal_but_unchanged_score_is_not() -> None:
    initial = make_match(status="1H", minute=10, home_score=0, away_score=0)
    _, checkpoint = diff_fixture(None, observation(initial), correlation_id=uuid7())
    changed = initial.model_copy(update={"minute": 20, "home_score": 1})
    goals, checkpoint = diff_fixture(
        checkpoint,
        observation(changed, observed_at=NOW + timedelta(minutes=10)),
        correlation_id=uuid7(),
    )
    assert [item.event_type for item in goals] == [FootballEventType.GOAL.value]
    unchanged, _ = diff_fixture(
        checkpoint,
        observation(changed, observed_at=NOW + timedelta(minutes=11)),
        correlation_id=uuid7(),
    )
    assert unchanged == []


def test_late_stale_snapshot_discovers_event_without_regressing_match_state() -> None:
    late_goal = event("late-goal", "Goal", 35, side="away", player="L. Noor")
    previous = {
        "version": 10,
        "status_code": "2H",
        "minute": 79,
        "home_score": 2,
        "away_score": 1,
        "event_ids": [],
        "scheduled_kickoff": make_match().kickoff_at.isoformat(),
        "kickoff_emitted": True,
        "halftime_emitted": True,
        "second_half_emitted": True,
    }
    stale = make_match(status="1H", minute=35, home_score=1, away_score=0, events=(late_goal,))
    created, checkpoint = diff_fixture(previous, observation(stale), correlation_id=uuid7())
    assert any(item.event_type == FootballEventType.GOAL.value for item in created)
    assert any(item.event_type == FootballEventType.SCORE_CORRECTED.value for item in created)
    assert checkpoint["status_code"] == "2H"
    assert checkpoint["minute"] == 79
    assert (checkpoint["home_score"], checkpoint["away_score"]) == (2, 1)


def test_provider_health_reports_rate_limit_and_persistent_auth_failure() -> None:
    health = ProviderHealthRegistry()
    cooldown = NOW + timedelta(minutes=3)
    state = health.rate_limited("football", "rate_limited", cooldown)
    assert state.status == "rate_limited"
    assert state.rate_limited_until == cooldown
    auth_failure = health.failure("football", "authentication_failed", immediate_unavailable=True)
    assert auth_failure.status == "auth_failure"
    assert auth_failure.consecutive_failures == 2


@pytest.mark.asyncio
async def test_source_filters_leagues_batches_live_details_and_serves_fixture_lists() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/leagues":
            payload = fixture_json("leagues_current.json")
        elif "from" in request.url.params:
            if request.url.params["league"] == "39":
                payload = fixture_json("fixtures_today.json")
            else:
                payload = {"errors": [], "results": 0, "response": []}
        elif "live" in request.url.params:
            payload = fixture_json("fixtures_live.json")
        elif "ids" in request.url.params:
            payload = fixture_json("fixtures_by_ids.json")
        else:
            raise AssertionError(f"unexpected provider request: {request.url.path}")
        return httpx.Response(200, json=payload)

    store = MemoryStore()
    source = FootballPollSource.from_configuration(
        "fixture-test-key",
        store=store,  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )
    assert source is not None
    try:
        context = PollContext(correlation_id=uuid7(), scheduled_at=NOW)
        results = await source.observe(context=context)
        service = source.fixtures_service
    finally:
        await source.close()
    live = next(item.content for item in results if item.content.fixture_id == 190001)
    assert live.status_code == "2H"
    assert len(live.events) == 5
    assert len(requests) == 14
    assert requests[0].url.path == "/leagues"
    schedule_requests = [request for request in requests if "from" in request.url.params]
    assert len(schedule_requests) == 11
    assert all(
        request.url.params["from"] == "2026-09-12"
        and request.url.params["to"] == "2026-09-18"
        and request.url.params["timezone"] == "UTC"
        for request in schedule_requests
    )
    live_request = next(request for request in requests if "live" in request.url.params)
    details_request = next(request for request in requests if "ids" in request.url.params)
    assert live_request.url.params["live"] == "2-3-39-40-45-48-61-78-135-140-253"
    assert details_request.url.params["ids"] == "190001"
    assert [item.fixture_id for item in service.today(now=NOW)] == [190001, 190002]
    assert [item.fixture_id for item in service.upcoming(now=NOW)] == [190002]
    assert [item.fixture_id for item in service.live()] == [190001]


def test_empty_database_checkpoint_store_constructs_without_network() -> None:
    assert FootballCheckpointStore() is not None
