"""Quota-aware async API-Football v3 client."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.providers.football.models import (
    ApiEnvelope,
    FixtureEnvelope,
    FixtureRecord,
    LeagueEnvelope,
    LeagueRecord,
)

log = logging.getLogger(__name__)
BASE_URL = "https://v3.football.api-sports.io"
MAX_FIXTURE_IDS = 20


class FootballApiError(Exception):
    def __init__(self, detail_code: str, *, permanent: bool = False) -> None:
        self.detail_code = detail_code
        self.permanent = permanent
        super().__init__(detail_code)


class FootballAuthenticationError(FootballApiError):
    def __init__(self) -> None:
        super().__init__("authentication_failed", permanent=True)


class FootballTransientError(FootballApiError):
    def __init__(self, detail_code: str = "provider_transient_failure") -> None:
        super().__init__(detail_code)


class FootballRateLimitError(FootballApiError):
    def __init__(self, retry_after: datetime, *, detail_code: str = "rate_limited") -> None:
        self.retry_after = retry_after.astimezone(UTC)
        super().__init__(detail_code)


class FootballQuotaBudgetError(FootballRateLimitError):
    def __init__(self, retry_after: datetime) -> None:
        super().__init__(retry_after, detail_code="daily_budget_depleted")


class DailyRequestBudget:
    """Local daily quota with a safety reserve and API-provided limit reconciliation."""

    def __init__(
        self,
        *,
        daily_limit: int = 100,
        safety_reserve: int = 5,
        persist: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.daily_limit = daily_limit
        self.safety_reserve = safety_reserve
        self.requests_used = 0
        self.requests_remaining_header: int | None = None
        self.requests_per_minute_remaining: int | None = None
        self._day: date | None = None
        self._persist = persist

    def restore(self, snapshot: Mapping[str, Any], *, now: datetime | None = None) -> None:
        current_day = (now or datetime.now(UTC)).astimezone(UTC).date()
        if snapshot.get("day") != current_day.isoformat():
            self._reset(current_day)
            return
        self._day = current_day
        self.daily_limit = _positive_int(snapshot.get("daily_limit"), fallback=100)
        self.requests_used = max(0, _integer(snapshot.get("requests_used"), 0))
        self.requests_remaining_header = _optional_nonnegative_int(
            snapshot.get("requests_remaining_header")
        )
        self.requests_per_minute_remaining = _optional_nonnegative_int(
            snapshot.get("requests_per_minute_remaining")
        )

    def can_request(self, *, now: datetime | None = None) -> bool:
        self._ensure_day(now)
        return self.remaining > self.safety_reserve

    @property
    def local_remaining(self) -> int:
        return max(0, self.daily_limit - self.requests_used)

    @property
    def remaining(self) -> int:
        if self.requests_remaining_header is None:
            return self.local_remaining
        return min(self.local_remaining, self.requests_remaining_header)

    def next_reset(self, *, now: datetime | None = None) -> datetime:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=UTC)

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self._ensure_day(current)
        return {
            "day": current.date().isoformat(),
            "requests_used": self.requests_used,
            "requests_remaining": self.remaining,
            "requests_remaining_header": self.requests_remaining_header,
            "local_remaining": self.local_remaining,
            "requests_per_minute_remaining": self.requests_per_minute_remaining,
            "daily_limit": self.daily_limit,
            "safety_reserve": self.safety_reserve,
            "next_reset_at": self.next_reset(now=current).isoformat(),
        }

    async def reserve(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self._ensure_day(current)
        if not self.can_request(now=current):
            raise FootballQuotaBudgetError(self.next_reset(now=current))
        self.requests_used += 1
        await self._save(current)

    async def update_headers(
        self, headers: Mapping[str, str], *, now: datetime | None = None
    ) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self._ensure_day(current)
        daily_limit = _optional_nonnegative_int(_header(headers, "x-ratelimit-requests-limit"))
        daily_remaining = _optional_nonnegative_int(
            _header(headers, "x-ratelimit-requests-remaining")
        )
        minute_remaining = _optional_nonnegative_int(_header(headers, "x-ratelimit-remaining"))
        if daily_limit:
            self.daily_limit = daily_limit
        if daily_remaining is not None:
            self.requests_remaining_header = daily_remaining
        if minute_remaining is not None:
            self.requests_per_minute_remaining = minute_remaining
        await self._save(current)

    async def _save(self, now: datetime) -> None:
        if self._persist:
            await self._persist(self.snapshot(now=now))

    def _ensure_day(self, now: datetime | None) -> None:
        current_day = (now or datetime.now(UTC)).astimezone(UTC).date()
        if self._day != current_day:
            self._reset(current_day)

    def _reset(self, current_day: date) -> None:
        self._day = current_day
        self.requests_used = 0
        self.requests_remaining_header = None
        self.requests_per_minute_remaining = None


class FootballApiClient:
    def __init__(
        self,
        api_key: str | SecretStr,
        *,
        budget: DailyRequestBudget | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | None = None,
        min_request_interval: float | None = None,
    ) -> None:
        key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not key or not key.strip():
            raise FootballAuthenticationError()
        self.budget = budget or DailyRequestBudget()
        # The free tier allows roughly ten requests per minute. Space live calls
        # proactively; fixture transports are test-only and stay fast by default.
        self._min_request_interval = (
            (0.0 if transport is not None else 6.1)
            if min_request_interval is None
            else max(0.0, min_request_interval)
        )
        self._request_lock = asyncio.Lock()
        self._last_request_started: float | None = None
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-apisports-key": key.strip(), "accept": "application/json"},
            timeout=timeout or httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def leagues_current(self) -> list[LeagueRecord]:
        return await self._all_pages("/leagues", {"current": "true"}, LeagueEnvelope)

    async def leagues_search(self, query: str, *, current_only: bool = True) -> list[LeagueRecord]:
        """Resolve one named league in a single metadata request for smoke checks."""

        params = {"search": query}
        if current_only:
            params["current"] = "true"
        response = await self._request("/leagues", params)
        return self._typed_response(LeagueEnvelope, response).response

    async def fixtures_by_date(self, fixture_date: date) -> list[FixtureRecord]:
        return await self._all_pages(
            "/fixtures",
            {"date": fixture_date.isoformat(), "timezone": "UTC"},
            FixtureEnvelope,
        )

    async def fixtures_by_competition_window(
        self,
        league_id: int,
        *,
        season: int | None,
        start: date,
        end: date,
    ) -> list[FixtureRecord]:
        params = {
            "league": str(league_id),
            "from": start.isoformat(),
            "to": end.isoformat(),
            "timezone": "UTC",
        }
        if season is not None:
            params["season"] = str(season)
        return await self._all_pages("/fixtures", params, FixtureEnvelope)

    async def live_fixtures(self, league_ids: list[int]) -> list[FixtureRecord]:
        if not league_ids:
            return []
        return await self._all_pages(
            "/fixtures",
            {"live": "-".join(str(item) for item in sorted(set(league_ids)))},
            FixtureEnvelope,
        )

    async def fixtures_by_ids(self, fixture_ids: list[int]) -> list[FixtureRecord]:
        unique_ids = sorted(set(fixture_ids))
        fixtures = []
        for offset in range(0, len(unique_ids), MAX_FIXTURE_IDS):
            batch = unique_ids[offset : offset + MAX_FIXTURE_IDS]
            if not batch:
                continue
            response = await self._request(
                "/fixtures", {"ids": "-".join(str(item) for item in batch)}
            )
            fixtures.extend(self._typed_response(FixtureEnvelope, response).response)
        return fixtures

    @staticmethod
    def _typed_response[ResponseT: ApiEnvelope](
        response_model: type[ResponseT], body: dict[str, Any]
    ) -> ResponseT:
        try:
            return response_model.model_validate(body)
        except ValidationError as exc:
            raise FootballTransientError("invalid_provider_response") from exc

    async def _all_pages[ResponseT: ApiEnvelope](
        self,
        path: str,
        params: dict[str, str],
        response_model: type[ResponseT],
    ) -> list[Any]:
        first = self._typed_response(response_model, await self._request(path, params))
        results = list(first.response)
        for page in range(first.paging.current + 1, first.paging.total + 1):
            paged = self._typed_response(
                response_model,
                await self._request(path, {**params, "page": str(page)}),
            )
            results.extend(paged.response)
        return results

    async def _request(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        await self._wait_for_request_slot()
        now = datetime.now(UTC)
        if not self.budget.can_request(now=now):
            raise FootballQuotaBudgetError(self.budget.next_reset(now=now))
        await self.budget.reserve(now=now)
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise FootballTransientError("provider_timeout") from exc
        except httpx.TransportError as exc:
            raise FootballTransientError("provider_transport_failure") from exc

        await self.budget.update_headers(response.headers, now=now)
        if response.status_code in (401, 403):
            raise FootballAuthenticationError()
        if response.status_code == 429:
            retry_at = _retry_after(response.headers.get("Retry-After"), now=now)
            if self.budget.remaining == 0:
                retry_at = max(retry_at, self.budget.next_reset(now=now))
            raise FootballRateLimitError(retry_at)
        if 500 <= response.status_code <= 599:
            raise FootballTransientError("provider_server_error")
        if response.status_code >= 400:
            raise FootballApiError("provider_request_rejected", permanent=True)

        try:
            body = response.json()
            envelope = ApiEnvelope.model_validate(body)
        except (ValueError, ValidationError) as exc:
            raise FootballTransientError("invalid_provider_response") from exc
        if envelope.errors:
            errors = envelope.errors
            error_values = errors.values() if isinstance(errors, dict) else errors
            error_text = " ".join(str(item).casefold() for item in error_values)
            if any(token in error_text for token in ("unauthorized", "invalid api key", "token")):
                raise FootballAuthenticationError()
            if "rate" in error_text and "limit" in error_text:
                raise FootballRateLimitError(self.budget.next_reset(now=now))
            raise FootballApiError("provider_response_error", permanent=True)
        if not isinstance(body, dict):
            raise FootballTransientError("invalid_provider_response")
        log.debug(
            "football provider request completed",
            extra={"provider": "football", "endpoint": path, "result_count": envelope.results},
        )
        return body

    async def _wait_for_request_slot(self) -> None:
        if self._min_request_interval <= 0:
            return
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            if self._last_request_started is not None:
                delay = self._min_request_interval - (loop.time() - self._last_request_started)
                if delay > 0:
                    await asyncio.sleep(delay)
            self._last_request_started = loop.time()


def _retry_after(value: str | None, *, now: datetime) -> datetime:
    if value:
        try:
            return now + timedelta(seconds=max(0, int(value.strip())))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(parsed.astimezone(UTC), now)
            except (TypeError, ValueError, OverflowError):
                pass
    return now + timedelta(minutes=1)


def _integer(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _positive_int(value: Any, *, fallback: int) -> int:
    candidate = _integer(value, fallback)
    return candidate if candidate > 0 else fallback


def _optional_nonnegative_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == target), None)
