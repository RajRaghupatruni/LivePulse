"""Minimal Gmail REST client; every endpoint is read-only and token-safe."""

import base64
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.providers.gmail.models import GmailMessageMetadata
from app.providers.gmail.oauth import GmailTokenManager, OAuthError
from app.providers.scheduler import RetryAfterError

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class GmailApiError(RuntimeError):
    def __init__(self, status_code: int, operation: str) -> None:
        self.status_code = status_code
        self.operation = operation
        self.detail_code = {
            401: "authorization_expired",
            403: "permission_denied",
            404: "resource_not_found",
            429: "rate_limited",
        }.get(status_code, "gmail_request_failed")
        super().__init__(self.detail_code)


class GmailApiClient:
    """Validated Gmail reads with one transparent access-token refresh on 401."""

    def __init__(self, http: httpx.AsyncClient, tokens: GmailTokenManager) -> None:
        self._http = http
        self._tokens = tokens

    async def profile_history_id(self) -> str:
        data = await self._request("GET", "/profile", operation="profile.get")
        return _history_id(data.get("historyId"))

    async def list_messages(
        self, *, limit: int, category: str, newer_than_days: int = 14
    ) -> list[tuple[str, str | None]]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if category not in {"recent", "unread", "initial"}:
            raise ValueError("unsupported Gmail message category")
        query = {
            "recent": f"newer_than:{newer_than_days}d",
            "unread": "is:unread",
            "initial": f"{{newer_than:{newer_than_days}d is:unread is:important}}",
        }[category]
        if not 1 <= newer_than_days <= 30:
            raise ValueError("newer_than_days must be between 1 and 30")
        data = await self._request(
            "GET",
            "/messages",
            operation="messages.list",
            params={"q": query, "maxResults": limit, "fields": "messages(id,threadId)"},
        )
        results: list[tuple[str, str | None]] = []
        for item in data.get("messages", [])[:limit]:
            if not isinstance(item, dict):
                continue
            message_id = _validated_id(item.get("id"))
            thread_id = _validated_id(item.get("threadId")) if item.get("threadId") else None
            if message_id:
                results.append((message_id, thread_id))
        return results

    async def message_metadata(self, message_id: str) -> GmailMessageMetadata:
        message_id = _validated_id(message_id)
        if message_id is None:
            raise ValueError("invalid Gmail message id")
        data = await self._request(
            "GET",
            f"/messages/{message_id}",
            operation="messages.get",
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"],
                "fields": "id,threadId,labelIds,internalDate,snippet,payload(headers)",
            },
        )
        return metadata_from_message(data)

    async def thread_messages(
        self, thread_id: str, *, limit: int = 50
    ) -> tuple[GmailMessageMetadata, ...]:
        thread_id = _validated_id(thread_id)
        if thread_id is None:
            raise ValueError("invalid Gmail thread id")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        data = await self._request(
            "GET",
            f"/threads/{thread_id}",
            operation="threads.get",
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"],
                "fields": "id,messages(id,threadId,labelIds,internalDate,snippet,payload(headers))",
            },
        )
        messages = data.get("messages", [])
        return tuple(
            metadata_from_message(item) for item in messages[:limit] if isinstance(item, dict)
        )

    async def history(self, *, start_history_id: str) -> tuple[str, list[dict[str, Any]]]:
        start_history_id = _history_id(start_history_id)
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        latest_id = start_history_id
        seen_page_tokens: set[str] = set()
        while len(records) < 50:
            params: dict[str, Any] = {
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
                "maxResults": 50,
                "fields": (
                    "historyId,nextPageToken,history(id,messagesAdded(message(id,threadId)),"
                    "messagesDeleted(message(id,threadId)),"
                    "labelsAdded(message(id,threadId)),labelsRemoved(message(id,threadId)))"
                ),
            }
            if page_token:
                params["pageToken"] = page_token
            data = await self._request("GET", "/history", operation="history.list", params=params)
            page_records = data.get("history", [])
            if isinstance(page_records, list):
                records.extend(
                    item for item in page_records[: 50 - len(records)] if isinstance(item, dict)
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                if data.get("historyId"):
                    latest_id = _history_id(data["historyId"])
                break
            if len(records) >= 50:
                if records:
                    latest_id = _history_id(records[-1].get("id"))
                break
            if not isinstance(page_token, str) or page_token in seen_page_tokens:
                raise GmailApiError(502, "history.pagination_invalid")
            seen_page_tokens.add(page_token)
        return latest_id, records

    async def message_body(
        self, message_id: str, *, max_chars: int = 100_000
    ) -> tuple[str, str, str]:
        message_id = _validated_id(message_id)
        if message_id is None:
            raise ValueError("invalid Gmail message id")
        if not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars must be between 1 and 100000")
        data = await self._request(
            "GET",
            f"/messages/{message_id}",
            operation="messages.body.get",
            params={"format": "full", "fields": "id,threadId,payload"},
        )
        message_metadata = metadata_from_message(data)
        text_parts: list[str] = []
        _extract_plain_text(data.get("payload") or {}, text_parts, max_chars)
        return message_id, message_metadata.thread_id, "\n".join(text_parts)[:max_chars]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._tokens.access_token()
        response = await self._http.request(
            method,
            f"{GMAIL_API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        )
        if response.status_code == 401:
            try:
                token = await self._tokens.access_token(force_refresh=True)
            except OAuthError:
                raise
            response = await self._http.request(
                method,
                f"{GMAIL_API}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            )
        if response.status_code == 429:
            raise RetryAfterError(_retry_after(response.headers.get("Retry-After")))
        if response.status_code >= 400:
            if response.status_code == 401:
                await self._tokens.reconnect_required()
            raise GmailApiError(response.status_code, operation)
        try:
            data = response.json()
        except ValueError as exc:
            raise GmailApiError(502, operation) from exc
        if not isinstance(data, dict):
            raise GmailApiError(502, operation)
        return data


def metadata_from_message(data: dict[str, Any]) -> GmailMessageMetadata:
    message_id = _validated_id(data.get("id"))
    thread_id = _validated_id(data.get("threadId"))
    if message_id is None or thread_id is None:
        raise GmailApiError(502, "messages.metadata")
    headers = _headers(data.get("payload"))
    sender = _safe_header(headers.get("from", ""), 320)
    subject = _safe_header(headers.get("subject", ""), 300) or "(no subject)"
    internal_date = data.get("internalDate")
    try:
        received = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        received = _parse_header_date(headers.get("date")) or datetime.now(UTC)
    labels = data.get("labelIds") if isinstance(data.get("labelIds"), list) else []
    snippet = _safe_snippet(data.get("snippet"))
    return GmailMessageMetadata(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        received_at=received,
        snippet=snippet,
        is_unread="UNREAD" in labels,
        is_important="IMPORTANT" in labels,
    )


def _headers(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    raw_headers = payload.get("headers")
    if not isinstance(raw_headers, list):
        return {}
    result: dict[str, str] = {}
    for header in raw_headers:
        if isinstance(header, dict) and isinstance(header.get("name"), str):
            name = header["name"].lower()
            if name in {"from", "subject", "date"} and isinstance(header.get("value"), str):
                result[name] = header["value"]
    return result


def _safe_header(value: str, limit: int) -> str:
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return value[:limit]


def _safe_snippet(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]{0,200}>", " ", value)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:240]


def _parse_header_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validated_id(value: object) -> str | None:
    return value if isinstance(value, str) and _MESSAGE_ID.fullmatch(value) else None


def _history_id(value: object) -> str:
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,32}", value):
        raise GmailApiError(502, "history_id.invalid")
    return value


def _retry_after(value: str | None) -> datetime:
    now = datetime.now(UTC)
    if value:
        try:
            return now + max(timedelta(seconds=float(value)), timedelta(0))
        except (ValueError, OverflowError):
            try:
                parsed = parsedate_to_datetime(value)
                return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
    return now + timedelta(minutes=1)


def _extract_plain_text(part: dict[str, Any], output: list[str], max_chars: int) -> None:
    if sum(map(len, output)) >= max_chars:
        return
    mime_type = part.get("mimeType")
    body = part.get("body")
    if mime_type == "text/plain" and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, str):
            try:
                encoded_limit = (max_chars * 4 + 2) // 3 + 4
                bounded_data = data[:encoded_limit]
                decoded = base64.urlsafe_b64decode(
                    bounded_data + "=" * (-len(bounded_data) % 4)
                ).decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                decoded = ""
            output.append(decoded[:max_chars])
    children = part.get("parts")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _extract_plain_text(child, output, max_chars)
