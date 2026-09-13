import asyncio
import logging
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from uuid6 import uuid7

from app.core.config import get_settings
from app.core.errors import LivePulseError, livepulse_error_handler
from app.core.health import component_snapshot, overall_status, report_component
from app.core.logging import configure_logging
from app.domain.focus import focus_for_match
from app.outbox.publisher import run_publisher
from app.projections.projector import run_projector
from app.providers.base import PollContext
from app.providers.football.models import FootballFixtureObservation
from app.providers.football.routes import router as football_router
from app.providers.football.source import FootballPollSource
from app.providers.gmail.models import GmailSyncBatch
from app.providers.gmail.oauth import encryption_key_configured, install_oauth_access_log_filter
from app.providers.gmail.router import router as gmail_oauth_router
from app.providers.gmail.sync import GmailSyncSource, ingest_gmail_observations
from app.providers.github.events import GithubChange
from app.providers.github.health import github_health
from app.providers.github.reconcile import GithubReconciliationSource
from app.providers.github.router import router as github_router
from app.providers.github.storage import persist_observations
from app.providers.observations import Observation
from app.providers.registry import ProviderRegistry
from app.providers.scheduler import PollScheduler
from app.providers.spotify.auth import is_spotify_configured
from app.providers.spotify.playback import SpotifyPlaybackChange
from app.providers.spotify.provider import spotify_provider
from app.providers.spotify.router import router as spotify_router
from app.providers.status import provider_health
from app.providers.weather.router import router as weather_router
from app.providers.weather.service import weather_state
from app.providers.weather.source import WeatherObservation, build_weather_source
from app.providers.weather.storage import persist_weather_observation
from app.realtime.manager import realtime
from app.simulator.comeback import activate_match, clear_demo_data, run_comeback
from app.storage.database import SessionFactory, engine, get_session
from app.storage.models import DemoControlRow, MatchStateRow, PulseTimelineRow

log = logging.getLogger(__name__)
router = APIRouter()
scenario_lock = asyncio.Lock()
scenario_task: asyncio.Task[None] | None = None
active_scenario_id: str | None = None


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("x-request-id") or str(uuid7())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        log.info(
            "request completed",
            extra={
                "request_id": request_id,
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
            },
        )
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    install_oauth_access_log_filter()
    report_component("demo_source", "healthy", "idle")
    settings = get_settings()
    github_health.initialize(settings)
    provider_registry = ProviderRegistry()
    provider_registry.register_command_target(spotify_provider.command_target)
    football_source: FootballPollSource | None = None
    if settings.provider_configuration()["football"]:
        football_source = FootballPollSource.from_configuration(settings.api_football_key)
        if football_source is not None:
            provider_registry.register_poll_source(football_source)
    if github_health.reconciliation_configured(settings):
        provider_registry.register_poll_source(GithubReconciliationSource(settings))
    if is_spotify_configured(settings):
        provider_registry.register_poll_source(spotify_provider.poll_source)
    if settings.provider_configuration()["gmail"] and encryption_key_configured(settings):
        provider_registry.register_poll_source(GmailSyncSource(settings=settings))
    elif settings.provider_configuration()["gmail"]:
        provider_health.report(
            "gmail", "degraded", "credential_encryption_unavailable", configured=True
        )
    weather_source = build_weather_source(settings)
    if weather_source is not None:
        provider_registry.register_poll_source(weather_source)

    async def persist_provider_observations(
        provider: str,
        observations: Sequence[Observation[BaseModel]],
        context: PollContext,
    ) -> None:
        if provider == "football":
            football_observations = [
                observation
                for observation in observations
                if isinstance(observation.content, FootballFixtureObservation)
            ]
            if len(football_observations) != len(observations) or football_source is None:
                raise ValueError("football source returned an unexpected observation type")
            await football_source.store.ingest(football_observations, context)
            await football_source.observations_persisted()
        elif provider == "github":
            github_observations = [
                observation
                for observation in observations
                if isinstance(observation.content, GithubChange)
            ]
            if len(github_observations) != len(observations):
                raise ValueError("GitHub source returned an unexpected observation type")
            try:
                await persist_observations(
                    github_observations, correlation_id=context.correlation_id
                )
            except Exception:
                github_health.note_reconciliation_failure("event_persist_failed")
                raise
        elif provider == "weather":
            weather_observations = [
                observation
                for observation in observations
                if isinstance(observation.content, WeatherObservation)
            ]
            if len(weather_observations) != len(observations):
                raise ValueError("weather source returned an unexpected observation type")
            for observation in weather_observations:
                try:
                    await persist_weather_observation(
                        observation.content,
                        observed_at=observation.observed_at,
                        correlation_id=context.correlation_id,
                    )
                except Exception:
                    weather_state.record_failure("event_persist_failed")
                    raise
        elif provider == "spotify":
            spotify_observations = [
                observation
                for observation in observations
                if isinstance(observation.content, SpotifyPlaybackChange)
            ]
            if len(spotify_observations) != len(observations):
                raise ValueError("Spotify source returned an unexpected observation type")
            await spotify_provider.event_sink.handle(provider, spotify_observations, context)
        elif provider == "gmail":
            gmail_observations = [
                observation
                for observation in observations
                if isinstance(observation.content, GmailSyncBatch)
            ]
            if len(gmail_observations) != len(observations):
                raise ValueError("Gmail source returned an unexpected observation type")
            await ingest_gmail_observations(provider, gmail_observations, context)
        else:
            raise ValueError("no ingestion adapter is registered for this provider")

    tasks: list[asyncio.Task[None]] = []
    poll_scheduler: PollScheduler | None = None
    if settings.run_background_services:
        tasks = [
            asyncio.create_task(run_publisher(), name="outbox-publisher"),
            asyncio.create_task(run_projector(), name="event-projector"),
        ]
        if provider_registry.poll_sources:
            scheduler = PollScheduler(
                provider_registry.poll_sources,
                observation_handler=persist_provider_observations,
                max_concurrency=2,
            )
            poll_scheduler = scheduler
            tasks.append(asyncio.create_task(scheduler.run(), name="provider-poll-scheduler"))
    _app.state.provider_registry = provider_registry
    yield
    global scenario_task
    if scenario_task is not None and not scenario_task.done():
        scenario_task.cancel()
        with suppress(asyncio.CancelledError):
            await scenario_task
    scenario_task = None
    if poll_scheduler is not None:
        await poll_scheduler.stop()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    if football_source is not None:
        await football_source.close()
    await engine.dispose()


async def _run_demo_scenario(match_id: str, run_id: Any) -> None:
    try:
        await run_comeback(match_id, run_id)
    except asyncio.CancelledError:
        report_component("demo_source", "healthy", "scenario_cancelled")
        raise
    except Exception:
        report_component("demo_source", "degraded", "scenario_failed")
        log.exception(
            "demo scenario failed",
            extra={"subject_id": match_id, "error_code": "demo_scenario_failed"},
        )
    else:
        report_component("demo_source", "healthy", "scenario_complete", succeeded=True)


app = FastAPI(title="LivePulse API", version="0.1.0", lifespan=lifespan)
app.include_router(football_router)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(LivePulseError, livepulse_error_handler)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed"
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request parameters are invalid",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    log.error(
        "unhandled request failure",
        extra={"request_id": request_id, "error_code": "internal_error"},
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "The request could not be completed",
                "request_id": request_id,
            }
        },
    )


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready() -> dict[str, str]:
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        producer = AIOKafkaProducer(
            bootstrap_servers=get_settings().kafka_bootstrap_servers, request_timeout_ms=1500
        )
        try:
            await producer.start()
        finally:
            with suppress(Exception):
                await producer.stop()
        return {"status": "ready"}
    except Exception as exc:
        raise LivePulseError(
            "dependencies_unavailable", "Database or event broker is unavailable", 503
        ) from exc


async def _probe_postgres() -> dict[str, Any]:
    try:
        async with SessionFactory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2)
        report_component("postgres", "healthy", "query_ok", succeeded=True)
    except Exception:
        report_component("postgres", "unavailable", "connection_failed")
    return component_snapshot("postgres")


async def _probe_redpanda() -> dict[str, Any]:
    producer = AIOKafkaProducer(
        bootstrap_servers=get_settings().kafka_bootstrap_servers,
        request_timeout_ms=2000,
    )
    try:
        await asyncio.wait_for(producer.start(), timeout=3)
        report_component("redpanda", "healthy", "broker_connected", succeeded=True)
    except Exception:
        report_component("redpanda", "unavailable", "broker_connection_failed")
    finally:
        with suppress(Exception):
            await producer.stop()
    return component_snapshot("redpanda")


@router.get("/api/v1/system/health")
async def system_health() -> dict[str, Any]:
    postgres, redpanda = await asyncio.gather(_probe_postgres(), _probe_redpanda())
    realtime_health = realtime.health_snapshot()
    components = {
        "postgres": postgres,
        "redpanda": redpanda,
        "outbox_publisher": component_snapshot("outbox_publisher"),
        "projector": component_snapshot("projector"),
        "realtime": realtime_health,
        "demo_source": component_snapshot("demo_source"),
    }
    return {
        "status": overall_status(components),
        "checked_at": datetime.now(UTC).isoformat(),
        "components": components,
        "providers": _provider_health_snapshot(),
    }


def _provider_health_snapshot() -> dict[str, dict[str, object]]:
    snapshots = provider_health.snapshot()
    if football_fixture_service.quota is not None:
        snapshots["football"]["quota"] = football_fixture_service.quota
    return snapshots


@router.get("/api/v1/live-state")
async def live_state(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    control = await session.get(DemoControlRow, 1)
    match = (
        await session.get(MatchStateRow, control.active_match_id)
        if control and control.active_match_id
        else None
    )
    if match is None:
        focus = focus_for_match("idle", None)
        return {
            "match": None,
            "attention": focus.score,
            "focus": focus.model_dump(mode="json"),
            "updated_at": None,
        }
    focus = focus_for_match(
        match.status,
        match.last_event_type,
        match.updated_at,
        source="football",
        subject_id=match.match_id,
    )
    return {
        "match": {
            "match_id": match.match_id,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "competition": match.competition,
            "home_score": match.home_score,
            "away_score": match.away_score,
            "status": match.status,
            "minute": match.minute,
            "phase": match.phase,
            "version": match.version,
            "last_event_id": str(match.last_event_id) if match.last_event_id else None,
            "last_event_type": match.last_event_type,
            "updated_at": match.updated_at.isoformat(),
        },
        "attention": focus.score,
        "focus": focus.model_dump(mode="json"),
        "updated_at": match.updated_at.isoformat(),
    }


@router.get("/api/v1/timeline")
async def timeline(
    limit: int = Query(default=50, ge=1, le=200),
    before: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(PulseTimelineRow).order_by(PulseTimelineRow.cursor.desc()).limit(limit)
    if before is not None:
        query = query.where(PulseTimelineRow.cursor < before)
    maximum = await session.scalar(select(func.max(PulseTimelineRow.cursor)))
    # Read the resume watermark first. A concurrent append can then be included
    # in the following page query without being skipped by a higher watermark.
    rows = list(await session.scalars(query))
    latest_cursor = max([maximum or 0, *(row.cursor for row in rows)])
    return {
        "items": [
            {
                "cursor": row.cursor,
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "source": row.source,
                "subject_id": row.subject_id,
                "timestamp": row.occurred_at.isoformat(),
                "payload": row.payload,
            }
            for row in rows
        ],
        "latest_cursor": latest_cursor,
    }


@router.post("/api/v1/demo/scenarios/comeback/start", status_code=202)
async def start_demo() -> dict[str, str]:
    global scenario_task, active_scenario_id
    async with scenario_lock:
        if scenario_task is not None and not scenario_task.done():
            raise LivePulseError(
                "scenario_already_running", "The comeback scenario is already running", 409
            )
        match_id = f"demo-{uuid7()}"
        run_id = await activate_match(match_id)
        active_scenario_id = match_id
        report_component("demo_source", "healthy", "scenario_running")
        scenario_task = asyncio.create_task(
            _run_demo_scenario(match_id, run_id), name="demo-comeback"
        )
        return {"status": "started", "scenario": "comeback", "match_id": match_id}


@router.post("/api/v1/demo/reset")
async def reset_demo() -> dict[str, str]:
    global scenario_task, active_scenario_id
    async with scenario_lock:
        if scenario_task is not None and not scenario_task.done():
            scenario_task.cancel()
            with suppress(asyncio.CancelledError):
                await scenario_task
        scenario_task = None
        active_scenario_id = None
        await clear_demo_data()
        report_component("demo_source", "healthy", "idle")
    await realtime.publish({"type": "resync_required", "reason": "demo_reset"})
    return {"status": "reset"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, last_cursor: int | None = None) -> None:
    await websocket.accept()
    queue = realtime.subscribe()
    try:
        if last_cursor is not None:
            async with SessionFactory() as session:
                latest = await session.scalar(select(func.max(PulseTimelineRow.cursor))) or 0
                if last_cursor > latest:
                    await websocket.send_json(
                        {
                            "type": "resync_required",
                            "reason": "cursor_ahead",
                            "latest_cursor": latest,
                        }
                    )
                else:
                    rows = list(
                        await session.scalars(
                            select(PulseTimelineRow)
                            .where(PulseTimelineRow.cursor > last_cursor)
                            .order_by(PulseTimelineRow.cursor)
                        )
                    )
                    for row in rows:
                        await websocket.send_json(
                            {
                                "type": "timeline.item",
                                "cursor": row.cursor,
                                "event_id": str(row.event_id),
                                "event_type": row.event_type,
                                "source": row.source,
                                "timestamp": row.occurred_at.isoformat(),
                                "payload": row.payload,
                                "replayed": True,
                            }
                        )
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_json(message)
            except TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        realtime.unsubscribe(queue)


app.include_router(router)
app.include_router(github_router)
app.include_router(spotify_router)
app.include_router(weather_router)
app.include_router(gmail_oauth_router)
