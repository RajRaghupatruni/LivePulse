"""Host and browser-origin boundary for the single-user local runtime."""

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from app.core.config import RuntimeMode, Settings

log = logging.getLogger(__name__)


class TrustedBoundaryMiddleware:
    """Reject untrusted hosts/origins before application routes or WebSockets run."""

    def __init__(self, app: Any, settings_getter: Callable[[], Settings]) -> None:
        self.app = app
        self.settings_getter = settings_getter

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        settings = self.settings_getter()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1")
        origin_value = headers.get(b"origin")
        origin = origin_value.decode("latin-1") if origin_value else None

        trusted_host = self._trusted_host(host, settings) or self._trusted_github_webhook_ingress(
            host, scope, settings
        )
        if not trusted_host:
            log.warning(
                "trusted boundary rejected request",
                extra={
                    "reason_code": "untrusted_host",
                    "request_type": scope.get("type"),
                    "host": host,
                },
            )
            await self._reject(scope, send, status=400, code="untrusted_host")
            return
        if origin is not None and not self._trusted_origin(origin, settings):
            log.warning(
                "trusted boundary rejected request",
                extra={
                    "reason_code": "untrusted_origin",
                    "request_type": scope.get("type"),
                    "host": host,
                    "origin": origin,
                },
            )
            await self._reject(scope, send, status=403, code="untrusted_origin")
            return
        if settings.runtime_mode is RuntimeMode.PUBLIC_DEMO and self._private_provider_path(scope):
            log.warning(
                "trusted boundary rejected request",
                extra={
                    "reason_code": "not_found",
                    "request_type": scope.get("type"),
                    "host": host,
                    "path": scope.get("path", ""),
                },
            )
            await self._reject(scope, send, status=404, code="not_found")
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _trusted_host(host_header: str, settings: Settings) -> bool:
        hostname = _parse_host(host_header)
        if hostname is None:
            return False
        if settings.runtime_mode is RuntimeMode.PERSONAL_LOCAL:
            return hostname in {"localhost", "127.0.0.1", "::1"}
        allowed = {_parse_host(value) for value in settings.public_demo_allowed_hosts}
        return hostname in allowed

    @staticmethod
    def _trusted_github_webhook_ingress(
        host_header: str, scope: dict[str, Any], settings: Settings
    ) -> bool:
        if (
            settings.runtime_mode is not RuntimeMode.PERSONAL_LOCAL
            or scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/v1/webhooks/github"
        ):
            return False
        if any(ord(character) <= 32 or ord(character) == 127 for character in host_header):
            return False
        if host_header.endswith(":"):
            return False
        try:
            raw_hostname = urlsplit("//" + host_header).hostname
        except ValueError:
            return False
        if raw_hostname is None or raw_hostname.endswith(".."):
            return False
        hostname = _parse_host(host_header)
        return hostname is not None and hostname in settings.github_webhook_allowed_hosts

    @staticmethod
    def _trusted_origin(origin: str, settings: Settings) -> bool:
        parsed = _parse_origin(origin)
        if parsed is None:
            return False
        if settings.runtime_mode is RuntimeMode.PERSONAL_LOCAL:
            browser_origin = parsed[1] in {"localhost", "127.0.0.1", "::1"}
            tauri_origin = origin == "http://tauri.localhost"
            if not browser_origin and not tauri_origin:
                return False
        return parsed in {_parse_origin(value) for value in settings.allowed_origins}

    @staticmethod
    def _private_provider_path(scope: dict[str, Any]) -> bool:
        path = scope.get("path", "")
        return path.startswith(("/api/v1/providers/", "/api/v1/webhooks/", "/api/v1/football"))

    @staticmethod
    async def _reject(scope: dict[str, Any], send: Any, *, status: int, code: str) -> None:
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = ('{"error":{"code":"' + code + '"}}').encode("ascii")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _parse_host(value: str) -> str | None:
    if not value or "@" in value or "/" in value or "\\" in value:
        return None
    try:
        parsed = urlsplit("//" + value)
        if parsed.path or parsed.query or parsed.fragment:
            return None
        _ = parsed.port
        return parsed.hostname.casefold().rstrip(".") if parsed.hostname else None
    except ValueError:
        return None


def _parse_origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port
        normalized_hostname = parsed.hostname.casefold().rstrip(".")
        normalized_port = f":{port}" if port else ""
        return (
            f"{parsed.scheme}://{normalized_hostname}{normalized_port}",
            parsed.hostname.casefold().rstrip("."),
            port,
        )
    except ValueError:
        return None
