"""Modular browser-facing Google OAuth routes; token material stays server-side."""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.core.config import RuntimeMode, get_settings
from app.providers.gmail.client import GmailApiError
from app.providers.gmail.models import GmailMessageMetadata
from app.providers.gmail.oauth import (
    GoogleOAuth,
    OAuthError,
    install_oauth_access_log_filter,
)
from app.providers.gmail.service import GmailReadOnlyService
from app.providers.status import provider_health
from app.storage.database import SessionFactory
from app.storage.models import ProviderCheckpointRow, ProviderConnectionRow

router = APIRouter(prefix="/api/v1/providers/gmail/oauth", tags=["gmail-oauth"])
connection_router = APIRouter(prefix="/api/v1/providers/gmail", tags=["gmail"])
install_oauth_access_log_filter()


def _frontend_oauth_result(result: str, reason: str | None = None) -> RedirectResponse:
    query = {"gmail": result}
    if reason is not None:
        query["reason"] = reason
    frontend_url = get_settings().frontend_base_url.rstrip("/")
    return RedirectResponse(f"{frontend_url}/?{urlencode(query)}", status_code=303)


@connection_router.delete("/connection")
async def disconnect_gmail() -> dict[str, object]:
    """Forget local Gmail credentials and sync cursors without deleting event history."""
    async with SessionFactory() as session:
        async with session.begin():
            connection = await session.scalar(
                select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
            )
            if connection is not None:
                connection.encrypted_credentials = None
                connection.status = "disconnected"
                connection.scopes = []
                connection.connected_at = None
            await session.execute(
                delete(ProviderCheckpointRow).where(ProviderCheckpointRow.provider == "gmail")
            )
    provider_health.report("gmail", "disconnected", "locally_disconnected", configured=True)
    return {
        "provider": "gmail",
        "connected": False,
        "status": "disconnected",
        "detail_code": "locally_disconnected",
    }


@connection_router.get("/messages")
async def recent_messages(limit: int = Query(default=4, ge=1, le=20)) -> dict[str, object]:
    """Return a small read-only inbox view with safe metadata only."""
    settings = get_settings()
    if settings.runtime_mode is not RuntimeMode.PERSONAL_LOCAL:
        return {"status": "not_configured", "configured": False, "messages": []}
    if not settings.provider_configuration()["gmail"]:
        return {"status": "not_configured", "configured": False, "messages": []}

    async with SessionFactory() as session:
        connection = await session.scalar(
            select(ProviderConnectionRow).where(ProviderConnectionRow.provider == "gmail")
        )
        connected = connection is not None and connection.status == "connected"
    if not connected:
        return {"status": "disconnected", "configured": True, "messages": []}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as http:
            service = GmailReadOnlyService.create(
                settings=settings, session_factory=SessionFactory, http=http
            )
            messages = await service.get_recent_messages(limit=limit)
    except OAuthError:
        return {"status": "disconnected", "configured": True, "messages": []}
    except (GmailApiError, httpx.HTTPError):
        return {"status": "unavailable", "configured": True, "messages": []}
    return {
        "status": "ready",
        "configured": True,
        "messages": [_message_payload(message) for message in messages],
    }


@connection_router.get("/messages/{message_id}")
async def message_metadata(message_id: str) -> dict[str, object]:
    """Return metadata for one message; the dashboard never fetches message bodies."""
    settings = get_settings()
    if (
        settings.runtime_mode is not RuntimeMode.PERSONAL_LOCAL
        or not settings.provider_configuration()["gmail"]
    ):
        raise HTTPException(status_code=404, detail="message_not_found")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as http:
            service = GmailReadOnlyService.create(
                settings=settings, session_factory=SessionFactory, http=http
            )
            message = await service.get_message_metadata(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="message_not_found") from exc
    except OAuthError as exc:
        raise HTTPException(status_code=503, detail=exc.detail_code) from exc
    except (GmailApiError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail="gmail_unavailable") from exc
    return _message_payload(message)


def _message_payload(message: GmailMessageMetadata) -> dict[str, object]:
    return message.model_dump(mode="json")


@router.get("/start", include_in_schema=False)
async def oauth_start() -> RedirectResponse:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as http:
            target = await GoogleOAuth(settings, SessionFactory, http).begin()
    except OAuthError as exc:
        raise _http_error(exc) from exc
    return RedirectResponse(target, status_code=302)


@router.get("/callback", include_in_schema=False)
async def oauth_callback(request: Request) -> RedirectResponse:
    settings = get_settings()
    state = request.query_params.get("state", "")
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if not state or len(state) > 200 or (code is not None and len(code) > 4096):
        return _frontend_oauth_result("error", "callback_invalid")
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as http:
        oauth = GoogleOAuth(settings, SessionFactory, http)
        if oauth.states is None:
            return _frontend_oauth_result("error", "setup_required")
        if error or not code:
            if not await oauth.states.consume(state):
                return _frontend_oauth_result("error", "state_invalid")
            if error:
                return _frontend_oauth_result("error", "authorization_denied")
            return _frontend_oauth_result("error", "authorization_incomplete")
        try:
            await oauth.complete(state=state, code=code)
        except OAuthError as exc:
            reason = {
                "oauth_state_invalid": "state_invalid",
                "authorization_code_invalid": "authorization_incomplete",
                "oauth_not_configured": "setup_required",
                "credential_encryption_unavailable": "setup_required",
            }.get(exc.detail_code, "connection_failed")
            return _frontend_oauth_result("error", reason)
        except httpx.HTTPError:
            return _frontend_oauth_result("error", "connection_failed")
    provider_health.report("gmail", "degraded", "initial_sync_pending", configured=True)
    return _frontend_oauth_result("connected")


@router.get("/complete", include_in_schema=False)
async def oauth_complete() -> dict[str, str]:
    return {"status": "connected", "provider": "gmail", "sync": "pending"}


def _http_error(error: OAuthError) -> HTTPException:
    status_code = (
        503
        if error.detail_code
        in {
            "oauth_not_configured",
            "credential_encryption_unavailable",
        }
        else 400
    )
    return HTTPException(status_code=status_code, detail=error.detail_code)
