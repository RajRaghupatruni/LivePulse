"""API-Football poll source and the provider-neutral fixture discovery service."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import SecretStr

from app.providers.base import PollContext, PollSchedule
from app.providers.football.api import (
    DailyRequestBudget,
    FootballApiClient,
    FootballRateLimitError,
)
from app.providers.football.cadence import CadenceDecision, adaptive_cadence_decision
from app.providers.football.leagues import resolve_league_metadata
from app.providers.football.models import (
    FixtureRecord,
    FootballFixtureObservation,
)
from app.providers.football.normalize import normalize_fixture
from app.providers.football.service import FootballFixtureService, football_fixture_service
from app.providers.football.store import FootballCheckpointStore
from app.providers.observations import Observation
from app.providers.scheduler import RetryAfterError
from app.providers.status import provider_health

CATALOG_TTL = timedelta(days=7)
CALENDAR_TTL = timedelta(hours=20)
LIVE_LOOKAHEAD = timedelta(hours=6)
DISCOVERY_HORIZON_DAYS = 7


class FootballPollSource:
    provider_id = "football"
    schedule = PollSchedule(
        interval=timedelta(hours=6),
        # Initial catalog + scoped fixture discovery is deliberately serialized
        # to honor the free-tier per-minute limit.
        timeout=timedelta(minutes=4),
        max_backoff=timedelta(hours=12),
        jitter_ratio=0.08,
    )

    def __init__(
        self,
        api: FootballApiClient,
        *,
        store: FootballCheckpointStore | None = None,
        fixture_service: FootballFixtureService | None = None,
        clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self.api = api
        self.store = store or FootballCheckpointStore()
        self._clock = clock
        self._initialized = False
        self._catalog: dict[str, int] = {}
        self._seasons: dict[str, int] = {}
        self._catalog_loaded_at: datetime | None = None
        self._fixtures: dict[int, FootballFixtureObservation] = {}
        self._pending_final_ids: set[int] = set()
        self._last_live_request_cost = 1
        self._cadence_decision: CadenceDecision | None = None
        self._fixture_service = fixture_service or football_fixture_service
        self._last_observation_at: datetime | None = None

    @classmethod
    def from_configuration(
        cls,
        api_key: str | SecretStr | None,
        *,
        store: FootballCheckpointStore | None = None,
        transport: Any = None,
        clock: Any = lambda: datetime.now(UTC),
    ) -> "FootballPollSource | None":
        value = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if value is None or not value.strip():
            return None
        actual_store = store or FootballCheckpointStore()

        async def persist_quota(snapshot: dict[str, Any]) -> None:
            await actual_store.put_json("quota:daily", snapshot, observed_at=clock())
            football_fixture_service.quota = snapshot

        budget = DailyRequestBudget(persist=persist_quota)
        api = FootballApiClient(api_key, budget=budget, transport=transport)
        return cls(api, store=actual_store, clock=clock)

    @property
    def fixtures_service(self) -> FootballFixtureService:
        return self._fixture_service

    def cadence(self, *, context: PollContext) -> timedelta:
        quota = self.api.budget.snapshot(now=context.scheduled_at)
        cadence_fixtures = [
            fixture.model_copy(update={"final_verification": True})
            if fixture.fixture_id in self._pending_final_ids
            else fixture
            for fixture in self._fixtures.values()
        ]
        decision = adaptive_cadence_decision(
            cadence_fixtures,
            now=context.scheduled_at,
            quota_remaining=int(quota["requests_remaining"]),
            minute_remaining=quota["requests_per_minute_remaining"],
            request_cost=self._last_live_request_cost,
        )
        if int(quota["requests_remaining"]) <= self.api.budget.safety_reserve:
            decision = CadenceDecision(
                max(
                    self.api.budget.next_reset(now=context.scheduled_at) - context.scheduled_at,
                    timedelta(seconds=1),
                ),
                "daily_budget_exhausted",
            )
            provider_health.rate_limited(
                self.provider_id,
                decision.reason,
                self.api.budget.next_reset(now=context.scheduled_at),
            )
        elif decision.reason.startswith("daily_quota_"):
            provider_health.report(
                self.provider_id,
                "degraded",
                decision.reason,
                configured=True,
            )
        self._cadence_decision = decision
        self._fixture_service.cadence = {
            "interval_seconds": decision.interval.total_seconds(),
            "reason": decision.reason,
            "request_cost": self._last_live_request_cost,
            "decided_at": context.scheduled_at.isoformat(),
        }
        return decision.interval

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "provider": provider_health.snapshot().get("football"),
            "quota": self.api.budget.snapshot(now=self._clock()),
            "cadence": self._fixture_service.cadence,
            "last_observation_at": (
                self._last_observation_at.isoformat() if self._last_observation_at else None
            ),
        }

    async def initialize(self) -> None:
        if self._initialized:
            return
        quota_state = await self.store.get_json("quota:daily")
        if quota_state:
            self.api.budget.restore(quota_state[0], now=self._clock())
        self._fixture_service.quota = self.api.budget.snapshot(now=self._clock())
        self._initialized = True

    async def observe(
        self, *, context: PollContext
    ) -> tuple[Observation[FootballFixtureObservation], ...]:
        try:
            return await self._observe(context)
        except FootballRateLimitError as exc:
            raise RetryAfterError(exc.retry_after, exc.detail_code) from exc

    async def _observe(
        self, context: PollContext
    ) -> tuple[Observation[FootballFixtureObservation], ...]:
        await self.initialize()
        now = self._clock().astimezone(UTC)
        await self._ensure_catalog(now)
        if not self._catalog:
            self._fixtures = {}
            self._fixture_service.replace([], observed_at=now)
            self._last_observation_at = now
            return ()

        today = now.date()
        horizon_end = today + timedelta(days=DISCOVERY_HORIZON_DAYS - 1)
        by_id: dict[int, FootballFixtureObservation] = {}
        for fixture in await self._calendar_window(today, horizon_end, now):
            by_id[fixture.fixture_id] = fixture

        pending_final_ids = set(await self._pending_final_verification_ids())
        pending_final_ids.update(self._pending_final_ids)
        self._pending_final_ids = pending_final_ids
        updated_dates: set[date] = set()
        if self._should_poll_live(tuple(by_id.values()), now):
            before_live_query = self.api.budget.requests_used
            live_records = await self.api.live_fixtures(list(self._catalog.values()))
            normalized_live = self._normalize_records(live_records)
            live_ids = {record.fixture.id for record in live_records}
            details_ids = {record.fixture.id for record in live_records if record.events is None}
            details_ids.update(
                fixture.fixture_id
                for fixture in by_id.values()
                if fixture.fixture_id not in live_ids
                and (
                    fixture.status_code in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}
                    or (
                        fixture.status_code in {"NS", "TBD", "PST"}
                        and now - timedelta(hours=4) <= fixture.kickoff_at <= now
                    )
                )
            )
            if details_ids:
                detailed = await self.api.fixtures_by_ids(sorted(details_ids))
                details_by_id = {item.fixture.id: item for item in detailed}
                normalized_live = self._merge_records(
                    normalized_live,
                    self._normalize_records(list(details_by_id.values())),
                )
            self._last_live_request_cost = max(1, self.api.budget.requests_used - before_live_query)
            by_id.update({fixture.fixture_id: fixture for fixture in normalized_live})
            updated_dates.update(fixture.kickoff_at.date() for fixture in normalized_live)

        if pending_final_ids:
            final_records = await self.api.fixtures_by_ids(pending_final_ids)
            final_snapshots = self._normalize_records(final_records)
            for fixture in final_snapshots:
                by_id[fixture.fixture_id] = fixture.model_copy(update={"final_verification": True})
            updated_dates.update(fixture.kickoff_at.date() for fixture in final_snapshots)

        # Keep discovery metadata current so a completed match does not remain a
        # stale "live" candidate and consume quota after its final verification.
        if updated_dates:
            await self.store.put_json(
                self._calendar_key(today, horizon_end),
                {
                    "items": [
                        item.model_copy(update={"final_verification": False}).model_dump(
                            mode="json"
                        )
                        for item in by_id.values()
                    ]
                },
                observed_at=now,
            )

        self._fixtures = by_id
        self._fixture_service.replace(list(by_id.values()), observed_at=now)
        self._last_observation_at = now
        return tuple(
            Observation[FootballFixtureObservation](
                provider_id=self.provider_id,
                external_entity_id=fixture.external_entity_id,
                observed_at=now,
                content=fixture,
                provider_version=fixture.status_code,
                correlation_id=context.correlation_id,
            )
            for fixture in sorted(
                by_id.values(), key=lambda item: (item.kickoff_at, item.fixture_id)
            )
        )

    async def close(self) -> None:
        await self.api.close()

    async def observations_persisted(self) -> None:
        self._pending_final_ids = set(await self._pending_final_verification_ids())
        self._fixtures = {
            fixture_id: fixture.model_copy(update={"final_verification": False})
            if fixture.final_verification and fixture_id not in self._pending_final_ids
            else fixture
            for fixture_id, fixture in self._fixtures.items()
        }
        self._fixture_service.replace(
            list(self._fixtures.values()), observed_at=self._last_observation_at
        )

    async def _ensure_catalog(self, now: datetime) -> None:
        if self._catalog_loaded_at and now - self._catalog_loaded_at < CATALOG_TTL:
            return
        cached = await self.store.get_json("league-catalog")
        if cached and cached[1] and now - cached[1] < CATALOG_TTL:
            catalog = cached[0].get("resolved")
            if isinstance(catalog, dict):
                self._catalog = {str(name): int(value) for name, value in catalog.items()}
                seasons = cached[0].get("seasons", {})
                if isinstance(seasons, dict):
                    self._seasons = {str(name): int(year) for name, year in seasons.items()}
                self._catalog_loaded_at = cached[1]
                return
        records = await self.api.leagues_current()
        self._catalog, self._seasons = resolve_league_metadata(records)
        self._catalog_loaded_at = now
        await self.store.put_json(
            "league-catalog",
            {"resolved": self._catalog, "seasons": self._seasons},
            observed_at=now,
        )

    async def _calendar_window(
        self, start: date, end: date, now: datetime
    ) -> list[FootballFixtureObservation]:
        key = self._calendar_key(start, end)
        cached = await self.store.get_json(key)
        if cached and cached[1] and now - cached[1] < CALENDAR_TTL:
            return self._deserialize_fixtures(cached[0].get("items", []))
        records: list[FixtureRecord] = []
        for competition, league_id in self._catalog.items():
            records.extend(
                await self.api.fixtures_by_competition_window(
                    league_id,
                    season=self._seasons.get(competition),
                    start=start,
                    end=end,
                )
            )
        fixtures = self._normalize_records(records)
        encoded = [fixture.model_dump(mode="json") for fixture in fixtures]
        await self.store.put_json(key, {"items": encoded}, observed_at=now)
        return fixtures

    @staticmethod
    def _calendar_key(start: date, end: date) -> str:
        return f"calendar-window:{start.isoformat()}:{end.isoformat()}"

    async def _pending_final_verification_ids(self) -> list[int]:
        checkpoint = await self.store.get_json("pending-final")
        if not checkpoint:
            return []
        values = checkpoint[0].get("fixture_ids", [])
        if not isinstance(values, list):
            return []
        return sorted({int(value) for value in values if str(value).isdigit()})

    def _normalize_records(self, records: list[FixtureRecord]) -> list[FootballFixtureObservation]:
        canonical = {league_id: name for name, league_id in self._catalog.items()}
        normalized = [
            item
            for record in records
            if (item := normalize_fixture(record, canonical_competitions=canonical)) is not None
        ]
        return normalized

    @staticmethod
    def _merge_records(
        first: list[FootballFixtureObservation], second: list[FootballFixtureObservation]
    ) -> list[FootballFixtureObservation]:
        by_id = {item.fixture_id: item for item in first}
        by_id.update({item.fixture_id: item for item in second})
        return list(by_id.values())

    @staticmethod
    def _deserialize_fixtures(items: Any) -> list[FootballFixtureObservation]:
        results = []
        if not isinstance(items, list):
            return results
        for item in items:
            try:
                results.append(FootballFixtureObservation.model_validate(item))
            except Exception:
                continue
        return results

    @staticmethod
    def _should_poll_live(fixtures: tuple[FootballFixtureObservation, ...], now: datetime) -> bool:
        for fixture in fixtures:
            if fixture.status_code in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}:
                return True
            if fixture.status_code in {"NS", "TBD", "PST"} and (
                now - timedelta(hours=4) <= fixture.kickoff_at <= now + LIVE_LOOKAHEAD
            ):
                return True
        return False
