"""Validated read-only Gmail service boundary for dashboard and future M4 tools."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.providers.gmail.client import GmailApiClient
from app.providers.gmail.models import GmailMessageBody, GmailMessageMetadata, GmailThreadMetadata
from app.providers.gmail.oauth import GmailTokenManager, GoogleOAuth


class GmailReadOnlyService:
    def __init__(self, api: GmailApiClient) -> None:
        self._api = api

    @classmethod
    def create(
        cls,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        http: httpx.AsyncClient,
    ) -> "GmailReadOnlyService":
        oauth = GoogleOAuth(settings, session_factory, http)
        tokens = GmailTokenManager(settings, session_factory, oauth)
        return cls(GmailApiClient(http, tokens))

    async def get_recent_messages(
        self, *, limit: int = 25, newer_than_days: int = 14
    ) -> tuple[GmailMessageMetadata, ...]:
        _validate_limit(limit)
        if not 1 <= newer_than_days <= 30:
            raise ValueError("newer_than_days must be between 1 and 30")
        ids = await self._api.list_messages(
            limit=limit, category="recent", newer_than_days=newer_than_days
        )
        return await self._hydrate(ids, limit=limit)

    async def get_unread_messages(self, *, limit: int = 25) -> tuple[GmailMessageMetadata, ...]:
        _validate_limit(limit)
        ids = await self._api.list_messages(limit=limit, category="unread")
        return await self._hydrate(ids, limit=limit)

    async def get_message_metadata(self, message_id: str) -> GmailMessageMetadata:
        return await self._api.message_metadata(message_id)

    async def get_thread_metadata(self, thread_id: str, *, limit: int = 50) -> GmailThreadMetadata:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return GmailThreadMetadata(
            thread_id=thread_id,
            messages=await self._api.thread_messages(thread_id, limit=limit),
        )

    async def get_message_body_for_explicit_request(self, message_id: str) -> GmailMessageBody:
        """Fetch a bounded body ephemerally for a future explicitly requested AI answer."""

        found_id, thread_id, text = await self._api.message_body(message_id, max_chars=100_000)
        return GmailMessageBody(message_id=found_id, thread_id=thread_id, text=text)

    async def _hydrate(
        self, ids: list[tuple[str, str | None]], *, limit: int
    ) -> tuple[GmailMessageMetadata, ...]:
        messages: list[GmailMessageMetadata] = []
        seen: set[str] = set()
        for message_id, _thread_id in ids:
            if message_id in seen:
                continue
            seen.add(message_id)
            messages.append(await self._api.message_metadata(message_id))
            if len(messages) >= limit:
                break
        return tuple(messages)


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
