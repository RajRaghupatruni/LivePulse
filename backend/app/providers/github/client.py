"""Small, read-only GitHub REST client with stable safe error codes."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import SecretStr

ResponseTransport = Callable[
    [str, Mapping[str, str], float], Awaitable[tuple[int, Mapping[str, str], bytes]]
]


class GithubApiError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        detail_code: str,
        *,
        retry_after: datetime | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail_code = detail_code
        self.retry_after = retry_after
        super().__init__(detail_code)


def normalize_api_error(
    status_code: int, headers: Mapping[str, str] | None = None, *, now: datetime | None = None
) -> GithubApiError:
    headers = {key.casefold(): value for key, value in (headers or {}).items()}
    retry_after = _retry_time(headers, now=now)
    remaining = headers.get("x-ratelimit-remaining")
    if status_code == 429 or (status_code == 403 and (retry_after or remaining == "0")):
        return GithubApiError(status_code, "github_rate_limited", retry_after=retry_after)
    if status_code == 401:
        return GithubApiError(status_code, "github_unauthorized")
    if status_code == 403:
        return GithubApiError(status_code, "github_forbidden")
    if 500 <= status_code <= 599:
        return GithubApiError(status_code, "github_server_error")
    return GithubApiError(status_code, "github_api_error")


def _retry_time(headers: Mapping[str, str], *, now: datetime | None = None) -> datetime | None:
    value = headers.get("retry-after")
    current = now or datetime.now(UTC)
    if value:
        try:
            return current + timedelta(seconds=max(0, int(value)))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                return parsed.astimezone(UTC) if parsed.tzinfo else None
            except (TypeError, ValueError, OverflowError):
                pass
    reset = headers.get("x-ratelimit-reset")
    if reset:
        try:
            return datetime.fromtimestamp(int(reset), UTC)
        except (ValueError, OverflowError, OSError):
            return None
    return None


class GithubRestClient:
    api_root = "https://api.github.com"

    def __init__(
        self, token: SecretStr, *, transport: ResponseTransport | None = None, timeout: float = 15
    ) -> None:
        self._token = token.get_secret_value()
        self._transport = transport or _urlopen_transport
        self._timeout = timeout

    async def get_json(self, path: str, *, params: Mapping[str, str | int] | None = None) -> object:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.api_root}{path}{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LivePulse/1.0",
        }
        try:
            status, response_headers, body = await self._transport(url, headers, self._timeout)
        except (TimeoutError, URLError, OSError) as exc:
            raise GithubApiError(0, "github_network_error") from exc
        if not 200 <= status < 300:
            raise normalize_api_error(status, response_headers)
        try:
            return json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise GithubApiError(status, "github_invalid_response") from exc


async def _urlopen_transport(
    url: str, headers: Mapping[str, str], timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    def execute() -> tuple[int, Mapping[str, str], bytes]:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    return await asyncio.to_thread(execute)
