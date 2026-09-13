"""Bounded single-process polling with timeout, jitter, retry and graceful stop."""

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from uuid6 import uuid7

from app.providers.base import PollContext, PollSource
from app.providers.observations import Observation
from app.providers.status import ProviderHealthRegistry, provider_health

log = logging.getLogger(__name__)


class RetryAfterError(Exception):
    """A provider asked the scheduler to wait until an absolute UTC time."""

    def __init__(self, retry_after: datetime, detail_code: str = "rate_limited") -> None:
        if retry_after.tzinfo is None or retry_after.utcoffset() is None:
            raise ValueError("retry_after must be timezone-aware")
        self.retry_after = retry_after.astimezone(UTC)
        self.detail_code = _safe_error_code(detail_code)
        super().__init__(self.detail_code)


def next_poll_delay(
    *,
    interval: timedelta,
    failure_count: int,
    max_backoff: timedelta,
    jitter_ratio: float,
    random_value: float,
    retry_after: datetime | None = None,
    now: datetime | None = None,
) -> timedelta:
    """Calculate a capped exponential delay with bounded jitter and Retry-After floor."""

    if interval <= timedelta(0) or max_backoff <= timedelta(0):
        raise ValueError("interval and max_backoff must be positive")
    if failure_count < 0:
        raise ValueError("failure_count cannot be negative")
    if not 0 <= random_value <= 1 or not 0 <= jitter_ratio <= 1:
        raise ValueError("random_value and jitter_ratio must be between 0 and 1")
    base_seconds = interval.total_seconds()
    if failure_count:
        max_seconds = max_backoff.total_seconds()
        for _ in range(failure_count - 1):
            base_seconds = min(base_seconds * 2, max_seconds)
            if base_seconds >= max_seconds:
                break
    bounded_seconds = base_seconds
    jittered = bounded_seconds * (1 - jitter_ratio + 2 * jitter_ratio * random_value)
    if failure_count:
        jittered = min(jittered, max_backoff.total_seconds())
    delay = timedelta(seconds=max(jittered, 0.001))
    if retry_after is not None:
        if retry_after.tzinfo is None or retry_after.utcoffset() is None:
            raise ValueError("retry_after must be timezone-aware")
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        delay = max(delay, retry_after.astimezone(UTC) - current.astimezone(UTC), timedelta(0))
    return delay


class PollScheduler:
    def __init__(
        self,
        sources: Sequence[PollSource],
        *,
        observation_handler: Callable[
            [str, Sequence[Observation[BaseModel]], PollContext], Awaitable[None]
        ],
        max_concurrency: int = 2,
        health: ProviderHealthRegistry = provider_health,
        random_value: Callable[[], float] = random.random,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if len({source.provider_id for source in sources}) != len(sources):
            raise ValueError("poll sources must have unique provider ids")
        self._sources = tuple(sources)
        self._observation_handler = observation_handler
        self._limit = asyncio.Semaphore(max_concurrency)
        self._health = health
        self._random_value = random_value
        self._clock = clock
        self._stop = asyncio.Event()
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._source_locks = {
            source.provider_id: asyncio.Lock() for source in self._sources
        }

    async def run(self) -> None:
        if self._tasks:
            raise RuntimeError("poll scheduler is already running")
        self._stop.clear()
        tasks = tuple(
            asyncio.create_task(self._run_source(source), name=f"poll:{source.provider_id}")
            for source in self._sources
        )
        self._tasks = tasks
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks = ()

    async def stop(self) -> None:
        self._stop.set()
        tasks = self._tasks
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def poll_now(self, provider_id: str) -> Sequence[Observation[BaseModel]]:
        """Run one bounded poll through the same observation/persistence path."""
        source = next((item for item in self._sources if item.provider_id == provider_id), None)
        if source is None:
            raise KeyError(provider_id)
        context = PollContext(correlation_id=uuid7(), scheduled_at=self._clock())
        try:
            async with self._limit:
                observations = await asyncio.wait_for(
                    self._observe_and_handle(source, context),
                    timeout=source.schedule.timeout.total_seconds(),
                )
        except RetryAfterError as exc:
            self._health.rate_limited(provider_id, exc.detail_code, exc.retry_after)
            raise
        except TimeoutError:
            self._health.failure(provider_id, "poll_timeout")
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail_code = _safe_error_code(getattr(exc, "detail_code", "poll_failed"))
            self._health.failure(
                provider_id,
                detail_code,
                immediate_unavailable=bool(getattr(exc, "permanent", False)),
            )
            raise
        self._health.success(
            provider_id,
            observed=bool(observations),
            configured=bool(getattr(source, "configured", True)),
        )
        return observations

    async def _run_source(self, source: PollSource) -> None:
        try:
            await self._run_source_until_stop(source)
        except asyncio.CancelledError:
            if self._stop.is_set():
                return
            raise

    async def _run_source_until_stop(self, source: PollSource) -> None:
        failures = 0
        while not self._stop.is_set():
            now = self._clock()
            context = PollContext(correlation_id=uuid7(), scheduled_at=now)
            rate_limit_until: datetime | None = None
            try:
                async with self._limit:
                    observations = await asyncio.wait_for(
                        self._observe_and_handle(source, context),
                        timeout=source.schedule.timeout.total_seconds(),
                    )
                    self._health.success(
                        source.provider_id,
                        observed=bool(observations),
                        configured=bool(getattr(source, "configured", True)),
                    )
                failures = 0
            except asyncio.CancelledError:
                if self._stop.is_set():
                    return
                raise
            except RetryAfterError as exc:
                failures += 1
                rate_limit_until = exc.retry_after
                self._health.rate_limited(source.provider_id, exc.detail_code, exc.retry_after)
                log.warning(
                    "provider poll rate limited",
                    extra={
                        "provider": source.provider_id,
                        "error_code": _safe_error_code(exc.detail_code),
                    },
                )
            except TimeoutError:
                failures += 1
                self._health.failure(source.provider_id, "poll_timeout")
                log.warning(
                    "provider poll timed out",
                    extra={"provider": source.provider_id, "error_code": "poll_timeout"},
                )
            except Exception as exc:
                failures += 1
                detail_code = _safe_error_code(getattr(exc, "detail_code", "poll_failed"))
                self._health.failure(
                    source.provider_id,
                    detail_code,
                    immediate_unavailable=bool(getattr(exc, "permanent", False)),
                )
                log.error(
                    "provider poll failed",
                    extra={
                        "provider": source.provider_id,
                        "error_code": detail_code,
                        "error_type": type(exc).__name__,
                    },
                )

            try:
                interval = source.cadence(context=context)
            except Exception as exc:
                interval = source.schedule.interval
                self._health.failure(source.provider_id, "cadence_failed")
                log.error(
                    "provider cadence hook failed",
                    extra={
                        "provider": source.provider_id,
                        "error_code": "cadence_failed",
                        "error_type": type(exc).__name__,
                    },
                )
            if not isinstance(interval, timedelta) or interval <= timedelta(0):
                interval = source.schedule.interval
                self._health.failure(source.provider_id, "invalid_cadence")

            delay = next_poll_delay(
                interval=interval,
                failure_count=failures,
                max_backoff=source.schedule.max_backoff,
                jitter_ratio=source.schedule.jitter_ratio,
                random_value=self._random_value(),
                retry_after=rate_limit_until,
                now=self._clock(),
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay.total_seconds())
            except TimeoutError:
                pass

    async def _observe_and_handle(
        self, source: PollSource, context: PollContext
    ) -> Sequence[Observation[BaseModel]]:
        async with self._source_locks[source.provider_id]:
            observations = await source.observe(context=context)
            if observations:
                await self._observation_handler(source.provider_id, observations, context)
            return observations


def _safe_error_code(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"[a-z0-9_.-]{1,64}", value):
        return value
    return "poll_failed"
