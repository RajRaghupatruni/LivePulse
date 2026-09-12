import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any

from aiokafka import AIOKafkaProducer
from fastapi import APIRouter, Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from uuid6 import uuid7

from app.core.config import get_settings
from app.core.errors import LivePulseError, livepulse_error_handler
from app.core.logging import configure_logging
from app.domain.focus import attention_for
from app.outbox.publisher import run_publisher
from app.projections.projector import run_projector
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
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    tasks: list[asyncio.Task[None]] = []
    if get_settings().run_background_services:
        tasks = [
            asyncio.create_task(run_publisher(), name="outbox-publisher"),
            asyncio.create_task(run_projector(), name="event-projector"),
        ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    await engine.dispose()


app = FastAPI(title="LivePulse API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(LivePulseError, livepulse_error_handler)


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
        await producer.start()
        await producer.stop()
        return {"status": "ready"}
    except Exception as exc:
        raise LivePulseError(
            "dependencies_unavailable", "Database or event broker is unavailable", 503
        ) from exc


@router.get("/api/v1/live-state")
async def live_state(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    control = await session.get(DemoControlRow, 1)
    match = (
        await session.get(MatchStateRow, control.active_match_id)
        if control and control.active_match_id
        else None
    )
    if match is None:
        return {"match": None, "attention": attention_for("idle", None), "updated_at": None}
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
        "attention": attention_for(match.status, match.last_event_type),
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
    rows = list(await session.scalars(query))
    maximum = await session.scalar(select(func.max(PulseTimelineRow.cursor)))
    return {
        "items": [
            {
                "cursor": row.cursor,
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "subject_id": row.subject_id,
                "timestamp": row.occurred_at.isoformat(),
                "payload": row.payload,
            }
            for row in rows
        ],
        "latest_cursor": maximum or 0,
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
        scenario_task = asyncio.create_task(run_comeback(match_id, run_id), name="demo-comeback")
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
