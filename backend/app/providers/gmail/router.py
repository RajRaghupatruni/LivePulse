"""Modular browser-facing Google OAuth routes; token material stays server-side."""

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.providers.gmail.oauth import (
    GoogleOAuth,
    OAuthError,
    install_oauth_access_log_filter,
)
from app.providers.status import provider_health
from app.storage.database import SessionFactory
from app.storage.models import ProviderCheckpointRow, ProviderConnectionRow

router = APIRouter(prefix="/api/v1/providers/gmail/oauth", tags=["gmail-oauth"])
connection_router = APIRouter(prefix="/api/v1/providers/gmail", tags=["gmail"])
install_oauth_access_log_filter()


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
        raise HTTPException(status_code=400, detail="oauth_callback_invalid")
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as http:
        oauth = GoogleOAuth(settings, SessionFactory, http)
        if oauth.states is None:
            raise HTTPException(status_code=503, detail="oauth_not_configured")
        if error or not code:
            if not await oauth.states.consume(state):
                raise HTTPException(status_code=400, detail="oauth_state_invalid")
            if error:
                raise HTTPException(status_code=400, detail="authorization_denied")
            raise HTTPException(status_code=400, detail="authorization_code_missing")
        try:
            await oauth.complete(state=state, code=code)
        except OAuthError as exc:
            raise _http_error(exc) from exc
    provider_health.report("gmail", "degraded", "initial_sync_pending", configured=True)
    return RedirectResponse("/api/v1/providers/gmail/oauth/complete", status_code=303)


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
