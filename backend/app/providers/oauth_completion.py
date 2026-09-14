"""Fixed, secret-free OAuth completion surfaces shared by local providers."""

from enum import StrEnum
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse, RedirectResponse, Response


class OAuthCompletionMode(StrEnum):
    BROWSER = "browser"
    DESKTOP = "desktop"


_PROVIDER_NAMES = {"spotify": "Spotify", "gmail": "Gmail"}
_SAFE_MESSAGES = {
    "authorization_denied": (
        "Authorization was denied. You can close this window and return to LivePulse."
    ),
    "authorization_incomplete": "Authorization was incomplete. Return to LivePulse and try again.",
    "callback_invalid": "Authorization could not be verified. Return to LivePulse and try again.",
    "state_invalid": "Authorization could not be verified. Return to LivePulse and try again.",
    "setup_required": "Connection setup is unavailable. Check the local provider configuration.",
    "connection_failed": "Connection failed. Return to LivePulse and try again.",
}


def oauth_result(
    provider: str,
    mode: OAuthCompletionMode,
    *,
    connected: bool,
    frontend_base_url: str,
    reason: str | None = None,
) -> Response:
    """Return either the existing browser redirect or a fixed desktop completion page."""
    if mode is OAuthCompletionMode.DESKTOP:
        return _completion_page(provider, connected=connected, reason=reason)

    result = "connected" if connected else "error"
    query = {provider: result}
    if reason is not None:
        query["reason"] = reason
    return RedirectResponse(
        f"{frontend_base_url.rstrip('/')}/?{urlencode(query)}", status_code=303
    )


def _completion_page(provider: str, *, connected: bool, reason: str | None) -> HTMLResponse:
    name = _PROVIDER_NAMES.get(provider, "Provider")
    title = f"{name} connected to LivePulse" if connected else f"{name} connection not completed"
    message = (
        "You can close this window and return to LivePulse."
        if connected
        else _SAFE_MESSAGES.get(
            reason or "", "Connection failed. Return to LivePulse and try again."
        )
    )
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{title}</title></head><body><main><p>LIVEPULSE · {name.upper()}</p>"
        f"<h1>{title}</h1><p>{message}</p></main></body></html>"
    )
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Security-Policy": (
                "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
