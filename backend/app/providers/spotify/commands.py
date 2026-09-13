"""Spotify playback CommandTarget with a closed endpoint and method allowlist."""

from __future__ import annotations

from typing import Any

from app.providers.commands import CommandRequest, CommandResult
from app.providers.spotify.client import (
    SpotifyApiClient,
    SpotifyApiError,
    SpotifyAuthenticationRequired,
    SpotifyRateLimited,
)


class SpotifyCommandTarget:
    provider_id = "spotify"

    supported_commands = frozenset(
        {
            "spotify.play",
            "spotify.pause",
            "spotify.next",
            "spotify.previous",
            "spotify.seek",
            "spotify.volume",
            "spotify.transfer_device",
        }
    )

    def __init__(self, client: SpotifyApiClient) -> None:
        self._client = client

    async def execute(self, request: CommandRequest) -> CommandResult:
        if request.command not in self.supported_commands:
            return self._failure(request, "unsupported_command", "Unsupported Spotify command")
        try:
            method, path, params, body = self._request_for(request)
        except ValueError:
            return self._failure(request, "invalid_state", "Spotify command arguments are invalid")

        try:
            await self._client.request_player(method, path, params=params, json_body=body)
        except SpotifyAuthenticationRequired:
            return self._failure(request, "not_authenticated", "Spotify authorization is required")
        except SpotifyRateLimited as exc:
            seconds = max(0, int((exc.retry_after - self._client._now()).total_seconds() + 0.999))
            return self._failure(
                request,
                "rate_limited",
                f"Spotify rate limit; retry after {seconds} seconds",
            )
        except SpotifyApiError as exc:
            if exc.status_code == 403:
                return self._failure(
                    request,
                    "provider_error",
                    "Spotify denied playback control; Premium or an allowed device may be required",
                )
            if exc.status_code == 404:
                return self._failure(
                    request, "invalid_state", "Spotify has no active matching device"
                )
            if exc.status_code is not None and exc.status_code >= 500:
                return self._failure(
                    request, "provider_unavailable", "Spotify is temporarily unavailable"
                )
            return self._failure(request, "provider_error", "Spotify could not apply the command")
        return CommandResult(
            success=True,
            provider=self.provider_id,
            message="Spotify command accepted",
        )

    def _request_for(
        self, request: CommandRequest
    ) -> tuple[str, str, dict[str, str | int] | None, dict[str, Any] | None]:
        command = request.command
        args = request.arguments
        if command == "spotify.play":
            return "PUT", "/me/player/play", None, None
        if command == "spotify.pause":
            return "PUT", "/me/player/pause", None, None
        if command == "spotify.next":
            return "POST", "/me/player/next", None, None
        if command == "spotify.previous":
            return "POST", "/me/player/previous", None, None
        if command == "spotify.seek":
            if args.position_seconds is None or args.position_seconds < 0:
                raise ValueError("seek requires a nonnegative position")
            return "PUT", "/me/player/seek", {"position_ms": args.position_seconds * 1000}, None
        if command == "spotify.volume":
            if args.volume_percent is None or not 0 <= args.volume_percent <= 100:
                raise ValueError("volume must be between 0 and 100")
            return "PUT", "/me/player/volume", {"volume_percent": args.volume_percent}, None
        if command == "spotify.transfer_device":
            device_id = args.device_id
            if (
                not isinstance(device_id, str)
                or not device_id.strip()
                or any(ord(character) < 32 for character in device_id)
            ):
                raise ValueError("device ID must be nonempty")
            return "PUT", "/me/player", None, {"device_ids": [device_id.strip()]}
        raise ValueError("unsupported command")

    def _failure(self, request: CommandRequest, code: str, message: str) -> CommandResult:
        return CommandResult(
            success=False,
            provider=self.provider_id,
            error_code=code,  # type: ignore[arg-type]
            message=message,
        )
